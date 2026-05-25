# WebSocket URL patterns for the deploy app
# These are separate from HTTP urls.py — Channels routes WebSocket connections here
# Format is the same as urls.py but for WebSocket consumers instead of views

websocket_urlpatterns = [
    # WebSocket endpoint for real-time log streaming during cluster operations
    # Frontend connects to ws://host/ws/deploy/logs/ to receive live updates
    # path('ws/deploy/logs/', consumers.DeployLogConsumer.as_asgi()),  # uncommented when consumer is ready
]