# urls.py — HTTP URL patterns for the deploy app
# WebSocket patterns live in routing.py — kept separate because they use different routers

from django.urls import path
from . import views

urlpatterns = [
    # POST /deploy/trigger/ — starts the disaster recovery sequence
    # GET requests are blocked by @require_POST — prevents accidental triggers
    path('trigger/', views.trigger_destroy, name='deploy_trigger'),
]