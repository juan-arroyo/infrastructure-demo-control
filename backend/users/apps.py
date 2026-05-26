from django.apps import AppConfig


class UsersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'users'
    # Placeholder app for future user management extensions
    # Currently authentication is handled by Django's built-in auth system
    # This app exists to allow adding custom user models or profile logic later
    # without restructuring the project