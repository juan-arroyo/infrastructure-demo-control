from decouple import config

from .base import *

# Development environment settings — local Docker setup only
# Never use these settings in production

DEBUG = True

ALLOWED_HOSTS = ['localhost', '127.0.0.1']

# PostgreSQL connection — credentials come from docker-compose.yml environment variables
# Using decouple to read them cleanly without hardcoding
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