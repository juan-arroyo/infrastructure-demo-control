import os
import django
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings.dev')

django.setup()

# Import routing after django.setup() — otherwise apps are not loaded yet
from deploy.routing import websocket_urlpatterns

# ProtocolTypeRouter directs incoming connections to the correct handler based on protocol type
# — http: standard Django views (same as before)
# — websocket: Django Channels consumers (new — handles real-time log streaming)
application = ProtocolTypeRouter({
    'http': get_asgi_application(),
    'websocket': AuthMiddlewareStack(
        # AuthMiddlewareStack adds Django authentication to WebSocket connections
        # — allows us to check if the user is logged in before accepting the WebSocket
        URLRouter(websocket_urlpatterns)
    ),
})