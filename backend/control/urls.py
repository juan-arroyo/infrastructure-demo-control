from django.urls import path
from . import views

app_name = 'control'

urlpatterns = [
    # Main dashboard — entry point after login
    path('', views.dashboard, name='dashboard'),
]