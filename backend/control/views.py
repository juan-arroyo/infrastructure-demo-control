from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from hcloud import Client
from decouple import config

# Import server definitions from hetzner.py — single source of truth for cluster topology
# Avoids duplicating IPs and names across multiple files
from deploy.hetzner import PRIMARY_IPS


# login_required redirects unauthenticated users to LOGIN_URL defined in base.py
# — prevents anyone from accessing the dashboard without logging in first
@login_required
def dashboard(request):
    return render(request, 'control/dashboard.html')


@login_required
def cluster_status(request):
    """
    Returns an HTML fragment with the current status of the 3 cluster servers.
    Called by HTMX every 10 seconds — returns a partial, not a full page.
    Using a separate endpoint keeps the dashboard view simple and makes
    the status widget independently refreshable without reloading the whole page.
    """
    client = Client(token=config('HETZNER_API_TOKEN'))
    servers = client.servers.get_all()

    # Build a dict of name → status for quick lookup in the template
    # — 'running', 'off', 'initializing' are Hetzner status strings
    server_status = {s.name: s.status for s in servers}

    # The three nodes we expect — if a node is missing it shows as offline
    nodes = [
        {'name': 'k3s-server',  'role': 'Control Plane', 'ip': PRIMARY_IPS['k3s-server']},
        {'name': 'k3s-agent-1', 'role': 'Worker 1',      'ip': PRIMARY_IPS['k3s-agent-1']},
        {'name': 'k3s-agent-2', 'role': 'Worker 2',      'ip': PRIMARY_IPS['k3s-agent-2']},
    ]

    for node in nodes:
        node['status'] = server_status.get(node['name'], 'offline')

    return render(request, 'control/cluster_status.html', {'nodes': nodes})