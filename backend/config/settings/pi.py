from decouple import config
from .base import *

# Production settings for the Pi — La Sala de Control
# Cloudflare handles HTTPS externally — Django runs behind Nginx on HTTP internally

DEBUG = False

ALLOWED_HOSTS = ['control.jmarroyo.es', 'localhost', '127.0.0.1']

# Tell Django to trust requests coming from these origins
# — required for CSRF to work when Django is behind Nginx + Cloudflare
CSRF_TRUSTED_ORIGINS = [
    'https://control.jmarroyo.es',
    'http://localhost:8084',  # for local testing directly on the Pi
]

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('DB_NAME'),
        'USER': config('DB_USER'),
        'PASSWORD': config('DB_PASSWORD'),
        'HOST': config('DB_HOST'),
        'PORT': config('DB_PORT', default='5432'),
    }
}

# Django is behind Nginx which is behind Cloudflare
# — tell Django to trust the X-Forwarded-Proto header set by Nginx
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# Do not redirect to HTTPS — Cloudflare and Nginx handle this externally
# If Django also redirects, it creates an infinite redirect loop
SECURE_SSL_REDIRECT = False