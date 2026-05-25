from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    # Django built-in auth views — handles login, logout, password reset
    # We override the login template with our cyberpunk design in templates/registration/login.html
    path('', include('django.contrib.auth.urls')),
    # Our apps
    path('', include('control.urls')),
# Serve static files in development — in production Nginx handles this
] + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)