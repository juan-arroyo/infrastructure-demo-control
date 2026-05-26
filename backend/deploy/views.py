# views.py — HTTP endpoints for cluster operations
# The destroy endpoint launches a background thread so Django can respond immediately
# while the long-running infrastructure operations stream logs via WebSocket

import threading
import ansible_runner
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from .hetzner import destroy_cluster, create_cluster


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

def trigger_provisioning(log):
    """
    Executes provision.yml on the Pi using ansible-runner.
    ansible-runner is used instead of subprocess because it captures output line by line
    — each line is emitted to the WebSocket as it arrives, giving real-time feedback.

    The playbook lives in ~/job-tracker/ansible/ on the Pi — the same machine running
    this Django app. ansible-runner executes it locally, not via SSH to another machine.
    """
    import os

    log('⚙️  Triggering Ansible provisioning...')

    # Path to the ansible directory inside the cloned repo on the Pi
    ansible_dir = os.path.expanduser('~/job-tracker/ansible')

    result = ansible_runner.run(
        private_data_dir=ansible_dir,
        playbook='provision.yml',
        # Vault password loaded from environment — never hardcode secrets in source code
        cmdline=f'--vault-password-file <(echo {os.environ.get("ANSIBLE_VAULT_PASSWORD", "")})',
        event_handler=lambda event: _handle_ansible_event(event, log),
    )

    if result.rc == 0:
        log('✅ Provisioning completed successfully.')
    else:
        log(f'❌ Provisioning failed with return code {result.rc}')


def _handle_ansible_event(event, log):
    """
    Called by ansible-runner for each event during playbook execution.
    Filters out noise and only forwards meaningful task output to the WebSocket.
    """
    # Only forward lines that have actual content — ansible-runner emits many empty events
    stdout = event.get('stdout', '').strip()
    if stdout:
        log(f'⚙️  {stdout}')


def run_disaster_recovery():
    """
    Executes the full cluster rebuild sequence in a background thread.
    Running in a thread is essential — these operations take several minutes and
    blocking the Django request cycle would timeout the browser connection.
    """
    try:
        # Step 1 — destroy the existing cluster
        destroy_cluster(log=broadcast_log)

        # Step 2 — recreate the cluster with the same specs and reserved IPs
        create_cluster(log=broadcast_log)

        # Step 3 — trigger Ansible provisioning on the Pi
        trigger_provisioning(log=broadcast_log)

        broadcast_log('✅ Disaster recovery sequence complete.')

    except Exception as e:
        # Catch all exceptions so the thread never dies silently
        # — without this, failures would be invisible to the browser
        broadcast_log(f'❌ Error during disaster recovery: {str(e)}')


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

    # Launch the recovery sequence in a daemon thread
    # daemon=True means the thread won't prevent Django from shutting down
    thread = threading.Thread(target=run_disaster_recovery, daemon=True)
    thread.start()

    # Respond immediately — the browser will receive progress via WebSocket
    return JsonResponse({'status': 'started'})