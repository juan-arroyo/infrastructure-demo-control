# views.py — HTTP endpoints for cluster operations
# The destroy and backup endpoints launch a background thread so Django can respond immediately
# while the long-running infrastructure operations stream logs via WebSocket

import re
import threading
import ansible_runner
from decouple import config
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from .hetzner import pick_server_type, destroy_cluster, create_cluster


# Only ONE cluster operation (disaster recovery or backup) may run at a time.
# Without this, a backup could start on k3s-server while the DR is destroying it,
# or two DRs could fight over the same servers.
# A plain in-memory Lock is enough because Daphne runs as a single process on the Pi.
# threading.Lock (not RLock) can be released by a different thread than the one
# that acquired it — the view acquires it, the background thread releases it.
_operation_lock = threading.Lock()

# ANSI colour codes (e.g. "\x1b[0;32m") that Ansible may add to its output —
# they are meaningless in a browser, so they are stripped before broadcasting
_ANSI_ESCAPE = re.compile(r'\x1b\[[0-9;]*m')


def _busy_response():
    """409 Conflict — returned when another cluster operation is already running."""
    return JsonResponse({'error': 'Another operation is already running'}, status=409)


def broadcast_log(message):
    """
    Sends a log message to all browsers connected to the 'deploy_logs' WebSocket group.
    Extracted as a helper because both the thread and error handlers need to call it.

    async_to_sync is needed because channel_layer.group_send is async,
    but this function is called from a regular synchronous thread — not an async context.
    """
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        'deploy_logs',
        {
            # 'type' must match the method name in the Consumer — 'deploy_log' calls deploy_log()
            'type': 'deploy_log',
            'message': message,
        }
    )

def run_playbook(playbook, log, use_vault=False):
    """
    Executes a playbook from ~/job-tracker/ansible/ on the Pi using ansible-runner
    and returns its exit code (0 = success).
    ansible-runner is used instead of subprocess because it captures output line by line
    — each line is emitted to the WebSocket as it arrives, giving real-time feedback.

    The playbook lives in ~/job-tracker/ansible/ on the Pi — the same machine running
    this Django app. ansible-runner executes it locally, and the playbook itself
    connects via SSH to the Hetzner servers listed in inventory-provision.ini.

    use_vault: True only for playbooks that read the encrypted provision_secrets.yml
    (provision.yml). backup.yml does not need it, so the password never touches disk.
    """
    import os
    import tempfile

    # Path to the ansible directory inside the cloned repo on the Pi
    ansible_dir = config('ANSIBLE_DIR')

    # inventory-provision.ini contains the 3 Hetzner VPS IPs and SSH config
    # — without this, ansible-runner only sees implicit localhost and skips all plays
    cmdline = '--inventory inventory-provision.ini'

    vault_pass_file = None

    try:
        if use_vault:
            # ansible-runner does not run through bash, so bash features like <(echo ...)
            # do not work. The standard solution is to write the password to a temporary
            # file and pass the file path — ansible-playbook reads it and deletes nothing,
            # so we clean it up manually after the run.
            vault_password = os.environ.get('ANSIBLE_VAULT_PASSWORD', '')

            # delete=False because ansible-runner needs to read the file after we close it
            # — if delete=True, the file disappears as soon as the 'with' block ends
            with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
                f.write(vault_password)
                vault_pass_file = f.name

            cmdline += f' --vault-password-file {vault_pass_file}'

        result = ansible_runner.run(
            private_data_dir=ansible_dir,
            playbook=playbook,
            cmdline=cmdline,
            event_handler=lambda event: _handle_ansible_event(event, log),
        )

    finally:
        # Always delete the temp file — even if ansible-runner crashes
        # Leaving a plaintext password on disk, even temporarily, is a security risk
        if vault_pass_file and os.path.exists(vault_pass_file):
            os.unlink(vault_pass_file)

    return result.rc


def trigger_provisioning(log):
    """
    Executes provision.yml — rebuilds K3s, the runner and the app on the new servers.
    Behaviour unchanged: logs the result but does not raise on failure.
    """
    log('⚙️  Triggering Ansible provisioning...')

    rc = run_playbook('provision.yml', log, use_vault=True)

    if rc == 0:
        log('✅ Provisioning completed successfully.')
    else:
        log(f'❌ Provisioning failed with return code {rc}')


def _handle_ansible_event(event, log):
    """
    Called by ansible-runner for each event during playbook execution.
    Filters out noise and only forwards meaningful task output to the WebSocket.
    """
    # Only forward lines that have actual content — ansible-runner emits many empty events
    stdout = _ANSI_ESCAPE.sub('', event.get('stdout', ''))

    # A single event can contain several lines (e.g. a debug task printing a list).
    # Sending each line separately keeps the web terminal readable — HTML would
    # otherwise collapse the newlines and show everything as one long line.
    for line in stdout.splitlines():
        if line.strip():
            log(f'⚙️  {line.rstrip()}')


def run_disaster_recovery():
    """
    Executes the full cluster rebuild sequence in a background thread.
    Running in a thread is essential — these operations take several minutes and
    blocking the Django request cycle would timeout the browser connection.
    """
    try:
        # Step 0 — pre-flight: make sure a server type is in stock BEFORE destroying anything.
        # If none is available, pick_server_type raises and the cluster is left untouched.
        server_type = pick_server_type(log=broadcast_log)

        # Step 1 — destroy the existing cluster
        destroy_cluster(log=broadcast_log)

        # Step 2 — recreate the cluster with the chosen server type and reserved IPs
        create_cluster(log=broadcast_log, server_type=server_type)

        # Step 3 — trigger Ansible provisioning on the Pi
        trigger_provisioning(log=broadcast_log)

        broadcast_log('✅ Disaster recovery sequence complete.')

    except Exception as e:
        # Catch all exceptions so the thread never dies silently
        # — without this, failures would be invisible to the browser
        broadcast_log(f'❌ Error during disaster recovery: {str(e)}')

    finally:
        # Always free the lock — even after an error — or no operation could ever run again
        _operation_lock.release()


def run_backup():
    """
    Forces an on-demand database backup in a background thread.
    backup.yml creates a Job from the db-backup CronJob on k3s-server, streams its log
    and fails if the Job fails — so a broken backup is never reported as success.
    Typical use: right before a disaster recovery, so no recent data is lost.
    """
    try:
        broadcast_log('💾 Starting on-demand database backup...')

        rc = run_playbook('backup.yml', broadcast_log)

        if rc == 0:
            broadcast_log('✅ Backup completed — safe to run disaster recovery.')
        else:
            broadcast_log(f'❌ Backup FAILED (return code {rc}) — do NOT run disaster recovery until it is fixed.')

    except Exception as e:
        # Same reason as in run_disaster_recovery — errors must reach the browser
        broadcast_log(f'❌ Error during backup: {str(e)}')

    finally:
        _operation_lock.release()


@login_required
@require_POST
def trigger_destroy(request):
    """
    POST endpoint that starts the disaster recovery sequence.
    Only admin users can trigger this — recruiter role is blocked at template level
    and here as a second layer of protection.
    """
    if not request.user.is_staff:
        return JsonResponse({'error': 'Admin only'}, status=403)

    # blocking=False: if another operation holds the lock, return immediately instead of waiting
    if not _operation_lock.acquire(blocking=False):
        return _busy_response()

    # Launch the recovery sequence in a daemon thread
    # daemon=True means the thread won't prevent Django from shutting down
    # The thread releases the lock when it finishes (see run_disaster_recovery)
    thread = threading.Thread(target=run_disaster_recovery, daemon=True)
    thread.start()

    # Respond immediately — the browser will receive progress via WebSocket
    return JsonResponse({'status': 'started'})


@login_required
@require_POST
def trigger_backup(request):
    """
    POST endpoint that starts an on-demand database backup.
    Admin only, same two layers of protection as trigger_destroy.
    """
    if not request.user.is_staff:
        return JsonResponse({'error': 'Admin only'}, status=403)

    if not _operation_lock.acquire(blocking=False):
        return _busy_response()

    # The thread releases the lock when it finishes (see run_backup)
    thread = threading.Thread(target=run_backup, daemon=True)
    thread.start()

    return JsonResponse({'status': 'started'})