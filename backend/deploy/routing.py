from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    # re_path used instead of path — WebSocket URLs often use regex for flexibility
    re_path(r'ws/deploy/logs/$', consumers.DeployLogConsumer.as_asgi()),
]