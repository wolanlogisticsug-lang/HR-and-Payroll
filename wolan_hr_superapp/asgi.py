"""
ASGI config for wolan_hr_superapp project.

It exposes the ASGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/5.1/howto/deployment/wsgi/
"""

import os

from django.core.asgi import get_asgi_application

# Fixed the space and casing right here:
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wolan_hr_superapp.settings')

application = get_asgi_application()