from django.urls import path
from . import views

app_name = 'control'

urlpatterns = [
    # Main dashboard — entry point after login
    path('', views.dashboard, name='dashboard'),
    # Cluster status fragment — polled by HTMX every 10 seconds
    # Returns a partial HTML response, not a full page
    path('cluster-status/', views.cluster_status, name='cluster_status'),
]