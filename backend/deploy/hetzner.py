# hetzner.py — all infrastructure operations against the Hetzner Cloud API
# Kept separate from views and consumers because infrastructure logic should not
# depend on HTTP or WebSocket concerns — this module only knows about servers

from hcloud import Client
from hcloud.servers.domain import Server
from hcloud.server_types.domain import ServerType
from hcloud.images.domain import Image
from hcloud.ssh_keys.domain import SSHKey
from decouple import config
import time

# Read the API token from environment — never hardcode credentials in source code
client = Client(token=config('HETZNER_API_TOKEN'))

# Server definitions — same names and location as the original cluster built in Module 3
# Using a list of dicts so adding or removing nodes requires changing one place only
# Location must stay hel1: the reserved Primary IPs belong to Helsinki and cannot move
SERVERS = [
    {
        'name': 'k3s-server',
        'location': 'hel1',
    },
    {
        'name': 'k3s-agent-1',
        'location': 'hel1',
    },
    {
        'name': 'k3s-agent-2',
        'location': 'hel1',
    },
]

# Server types to try, in order of preference (prices: Hetzner API, hel1, Nov 2026, excl. VAT)
#   cx23  — 2 vCPU / 4 GB, €0.0088/h — cheapest, but often out of stock in 2026
#   cpx22 — 2 vCPU / 4 GB, €0.0312/h — same resources as cx23, the direct replacement
#   cpx32 — 4 vCPU / 8 GB, €0.0569/h — second fallback
#   ccx13 — 2 dedicated vCPU / 8 GB, €0.0689/h — last resort
# Only x86 types: the GitHub runner download (x64) and the Docker image (amd64) are x86-only,
# so ARM 'cax' types would break provisioning. 1 GB types (cpx02) are too small for K3s + PostgreSQL.
SERVER_TYPE_PREFERENCE = ['cx23', 'cpx22', 'cpx32', 'ccx13']

# Primary IPs are reserved in Hetzner — auto_delete is disabled so they survive
# a full cluster destruction. We reassign them on creation to keep DNS records intact.
# Without fixed IPs, every rebuild would require updating DNS and kubeconfig manually.
PRIMARY_IPS = {
    'k3s-server':  '46.62.219.138',
    'k3s-agent-1': '77.42.124.22',
    'k3s-agent-2': '77.42.124.11',
}

# SSH key name as registered in Hetzner — injected automatically on server creation
# The key must already exist in Hetzner Security → SSH Keys before running this
SSH_KEY_NAME = config('HETZNER_SSH_KEY_NAME')


def pick_server_type(log, location='hel1'):
    """
    Pre-flight check: returns the first type of SERVER_TYPE_PREFERENCE that Hetzner can
    create right now in the given location, or raises if none is available.

    MUST run BEFORE destroy_cluster — otherwise the cluster could be destroyed and then
    fail to rebuild because the server type is out of stock.

    Uses the raw API on purpose: since 2026 availability lives in
    server_types[].locations[].available, a field the pinned hcloud 2.3.0 library
    does not know (the old /datacenters endpoint was removed by Hetzner).
    """
    log(f'🔎 Checking server type availability in {location}...')

    types = client.request('GET', '/server_types', params={'per_page': 50})['server_types']
    by_name = {t['name']: t for t in types}

    for name in SERVER_TYPE_PREFERENCE:
        server_type = by_name.get(name)
        # Find this type's entry for our location (None if the type is not offered there)
        loc = next((l for l in (server_type or {}).get('locations', []) if l.get('name') == location), None)

        if loc and loc.get('available'):
            log(f'✅ Using server type {name}')
            return name

        log(f'⚠️  {name} not available in {location} — trying the next one')

    # Nothing available: stop here, BEFORE anything has been destroyed
    raise Exception(
        f'No server type available in {location} '
        f'(tried {", ".join(SERVER_TYPE_PREFERENCE)}) — cluster left untouched'
    )


def destroy_cluster(log):
    """
    Deletes all three cluster servers via the Hetzner API.

    log: callable that accepts a string — used to stream progress to the caller
    (WebSocket consumer, CLI, test — this function does not care which)
    """
    log('💀 Initiating destruction sequence...')

    servers = client.servers.get_all()

    # Filter only the servers that belong to this cluster
    # — avoids accidentally deleting unrelated servers in the same Hetzner project
    cluster_names = {s['name'] for s in SERVERS}
    cluster_servers = [s for s in servers if s.name in cluster_names]

    if not cluster_servers:
        log('⚠️  No cluster servers found — nothing to destroy')
        return

    # Destroy workers first, then the control-plane
    # — cleaner shutdown order, mirrors how K3s recommends draining nodes before removing them
    ordered = sorted(cluster_servers, key=lambda s: (0 if 'agent' in s.name else 1))

    for server in ordered:
        log(f'🔴 Terminating {server.name}...')
        client.servers.delete(server)

    log('⚰️  Cluster destroyed. Total silence.')


def create_cluster(log, server_type):
    """
    Creates the three cluster servers with the given server type (chosen by pick_server_type).
    Assigns the reserved Primary IPs so DNS and kubeconfig remain valid after rebuild.
    log: callable that accepts a string — same pattern as destroy_cluster
    server_type: Hetzner server type name, e.g. 'cx23' or 'cpx22'
    """
    import socket

    log('⏳ Waiting before creating new servers...')
    # Hetzner needs time to fully release the Primary IPs after destruction
    # — without this pause, the API returns 'primary_ip_assigned' error
    time.sleep(30)

    # Fetch all authorized SSH keys — injected into every new server on creation
    ssh_keys = [
        client.ssh_keys.get_by_name('Key-Pi'),
        client.ssh_keys.get_by_name('Key-Ubuntu-Pc'),
        client.ssh_keys.get_by_name('Key-Ubuntu-Nb'),
    ]

    for server_def in SERVERS:
        log(f'🔨 Building {server_def["name"]} ({server_type})...')

        # Look up the reserved Primary IP for this server by its fixed IP address
        # — Primary IPs are Hetzner resources independent of servers, so they must
        #   be fetched and passed explicitly during server creation
        primary_ip_obj = _get_primary_ip(PRIMARY_IPS[server_def['name']])

        client.servers.create(
            name=server_def['name'],
            server_type=ServerType(name=server_type),
            image=Image(name='ubuntu-22.04'),
            location=client.locations.get_by_name(server_def['location']),
            ssh_keys=ssh_keys,
            # Assign the reserved Primary IP — keeps the same public IP after rebuild
            public_net=_build_public_net(primary_ip_obj),
        )

        log(f'✅ {server_def["name"]} created')

    log('🖥️  All servers created — waiting for SSH to become available...')

    # Actively poll SSH on each server instead of a fixed sleep
    # — a fixed sleep is unreliable because boot time varies between servers
    # — this loop only continues when all 3 servers are actually ready
    for server_def in SERVERS:
        ip = PRIMARY_IPS[server_def['name']]
        log(f'⏳ Waiting for SSH on {server_def["name"]} ({ip})...')

        # Try every 5 seconds for up to 5 minutes (60 attempts)
        # — 5 minutes is generous but Hetzner VPS rarely take longer than 2
        for attempt in range(60):
            try:
                # Try to open a TCP connection to port 22
                # — if it succeeds, SSH daemon is up and Ansible can connect
                sock = socket.create_connection((ip, 22), timeout=5)
                sock.close()
                log(f'✅ SSH ready on {server_def["name"]}')
                break
            except (socket.timeout, ConnectionRefusedError, OSError):
                # Not ready yet — wait 5 seconds and try again
                time.sleep(5)
        else:
            # The for loop completed without breaking — SSH never responded
            raise Exception(f'SSH timeout on {server_def["name"]} after 5 minutes')


def _get_primary_ip(ip_address):
    """
    Returns the Hetzner PrimaryIP object matching the given IP address string.
    Using a helper keeps create_cluster readable — IP lookup is a detail, not the main story.
    """
    all_primary_ips = client.primary_ips.get_all()
    for pip in all_primary_ips:
        if pip.ip == ip_address:
            return pip
    raise ValueError(f'Primary IP {ip_address} not found in Hetzner project')


def _build_public_net(primary_ip_obj):
    """
    Builds the public_net parameter required by the Hetzner API to assign a Primary IP.
    Extracted to a helper because the data structure is verbose and would clutter create_cluster.
    """
    from hcloud.servers.domain import ServerCreatePublicNetwork
    from hcloud.primary_ips.domain import PrimaryIP

    return ServerCreatePublicNetwork(
        ipv4=primary_ip_obj,
        enable_ipv6=False,  # IPv6 not needed — cluster communication is IPv4 only
    )