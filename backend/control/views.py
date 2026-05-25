from django.shortcuts import render
from django.contrib.auth.decorators import login_required

# login_required redirects unauthenticated users to LOGIN_URL defined in base.py
# — prevents anyone from accessing the dashboard without logging in first
@login_required
def dashboard(request):
    return render(request, 'control/dashboard.html')