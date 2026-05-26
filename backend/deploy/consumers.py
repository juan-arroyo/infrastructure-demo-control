# consumers.py — WebSocket consumer for real-time log streaming during cluster operations
# A Consumer is the WebSocket equivalent of a Django view — instead of request/response,
# it keeps a persistent connection open and can push messages to the browser at any time

import json
from channels.generic.websocket import AsyncWebsocketConsumer


class DeployLogConsumer(AsyncWebsocketConsumer):
    """
    Handles the WebSocket connection for the deployment log terminal.
    Each browser tab that opens the dashboard gets its own instance of this consumer.
    """

    async def connect(self):
        # Only authenticated users can open a WebSocket connection
        # — prevents anonymous users from monitoring cluster operations
        if not self.scope['user'].is_authenticated:
            await self.close()
            return

        # Each consumer joins a shared channel group named 'deploy_logs'
        # — this allows Django to broadcast a message to ALL connected browsers at once
        # — useful when admin triggers destruction and recruiter is watching simultaneously
        self.group_name = 'deploy_logs'

        await self.channel_layer.group_add(
            self.group_name,
            self.channel_name,
        )

        await self.accept()

    async def disconnect(self, close_code):
        # Remove this consumer from the group when the browser closes the connection
        # — avoids sending messages to dead connections
        await self.channel_layer.group_discard(
            self.group_name,
            self.channel_name,
        )

    async def receive(self, text_data):
        # We don't expect messages FROM the browser — the log is server → browser only
        # This method is required by the base class but intentionally left empty
        pass

    async def deploy_log(self, event):
        """
        Called by Django when someone broadcasts to the 'deploy_logs' group.
        Forwards the message to the browser as a JSON WebSocket frame.

        event: dict with a 'message' key — sent by the broadcast helper in views.py
        """
        await self.send(text_data=json.dumps({
            'message': event['message'],
        }))