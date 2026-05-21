"""
Django settings for aec_hr_superapp project.
AEC Group HR & Payroll Super App
"""
import os
from pathlib import Path
from decouple import config, Csv

# Force IPv4 for all socket connections to fix [Errno 101] Network is unreachable for SMTP
import socket
orig_getaddrinfo = socket.getaddrinfo
def getaddrinfo_ipv4(host, port, family=0, type=0, proto=0, flags=0):
    return orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)
socket.getaddrinfo = getaddrinfo_ipv4

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = config('SECRET_KEY', default='django-insecure-aec-hr-dev-key-change-in-production')
DEBUG = config('DEBUG', default=True, cast=bool)
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='*', cast=Csv())

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'cloudinary_storage',
    'cloudinary',
    'rest_framework',
    'django_extensions',
    'django_q',
    'core',
    'onboarding',
    'attendance',
    'payroll',
    'leave',
    'assets',
    'communications',
    'notifications',
]

# django-q2 — real worker via supervisor (program:qcluster). sync=True only
# kicks in if the worker is unavailable (allows tests to keep working).
Q_CLUSTER = {
    'name': 'aec_hr',
    'workers': 2,
    'recycle': 500,
    'timeout': 60,
    'retry': 120,
    'queue_limit': 50,
    'bulk': 5,
    'orm': 'default',
    'sync': config('Q_CLUSTER_SYNC', default=False, cast=bool),
    'log_level': 'INFO',
}

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.locale.LocaleMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'aec_hr_superapp.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'core.context_processors.breadcrumbs',
                'notifications.context_processors.notification_count',
                'core.context_processors.active_user_profile',
                'core.context_processors.global_wishes_and_alerts',
            ],
        },
    },
]

WSGI_APPLICATION = 'aec_hr_superapp.wsgi.application'

DATABASE_URL = config('DATABASE_URL')
import dj_database_url
DATABASES = {
    'default': dj_database_url.parse(DATABASE_URL, conn_max_age=600, conn_health_checks=True)
}

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

AUTH_USER_MODEL = 'core.User'

LANGUAGE_CODE = 'en'
LANGUAGES = [
    ('en', 'English'),
    ('ml', 'മലയാളം'),
]
LOCALE_PATHS = [BASE_DIR / 'locale']
TIME_ZONE = 'Asia/Kolkata'
USE_I18N = True
USE_TZ = True

STATIC_URL = '/static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': ['rest_framework.authentication.SessionAuthentication'],
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.IsAuthenticated'],
    'DEFAULT_PAGINATION_CLASS': 'rest_framework.pagination.PageNumberPagination',
    'PAGE_SIZE': 25,
}

LOGIN_URL = '/accounts/login/'
LOGIN_REDIRECT_URL = '/dashboard/'
LOGOUT_REDIRECT_URL = '/accounts/login/'

# CSRF-trusted origins (Emergent preview & cluster URLs).
# Wildcard subdomains for *.preview.emergentagent.com & *.preview.emergentcf.cloud
CSRF_TRUSTED_ORIGINS = config(
    'CSRF_TRUSTED_ORIGINS',
    default='https://*.preview.emergentagent.com,https://*.preview.emergentcf.cloud,http://localhost:3000,http://localhost:8001,http://localhost:8000,http://127.0.0.1:8000',
    cast=Csv(),
)

EMAIL_BACKEND = config('EMAIL_BACKEND', default='core.email_backends.BrevoEmailBackend')
BREVO_API_KEY = config('BREVO_API_KEY', default='')
EMAIL_HOST = config('EMAIL_HOST', default='smtp.gmail.com')
EMAIL_PORT = config('EMAIL_PORT', default=587, cast=int)
EMAIL_USE_TLS = config('EMAIL_USE_TLS', default=True, cast=bool)
EMAIL_HOST_USER = config('EMAIL_HOST_USER', default='mridhulasethu@gmail.com')
EMAIL_HOST_PASSWORD = config('EMAIL_HOST_PASSWORD', default='')
EMAIL_TIMEOUT = config('EMAIL_TIMEOUT', default=10, cast=int)  # Added to prevent Gunicorn worker timeout
DEFAULT_FROM_EMAIL = config('DEFAULT_FROM_EMAIL', default=EMAIL_HOST_USER)

GEOFENCE_RADIUS_METERS = 100
GRACE_PERIOD_MINUTES = 15

# Cloudinary Storage Configuration for Media uploads
CLOUDINARY_STORAGE = {
    'CLOUD_NAME': config('CLOUDINARY_CLOUD_NAME', default=''),
    'API_KEY': config('CLOUDINARY_API_KEY', default=''),
    'API_SECRET': config('CLOUDINARY_API_SECRET', default=''),
}

if CLOUDINARY_STORAGE['CLOUD_NAME']:
    STORAGES = {
        'default': {
            'BACKEND': 'cloudinary_storage.storage.MediaCloudinaryStorage',
        },
        'staticfiles': {
            'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
        },
    }
else:
    STORAGES = {
        'default': {
            'BACKEND': 'django.core.files.storage.FileSystemStorage',
        },
        'staticfiles': {
            'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage',
        },
    }

# Deprecated setting added for backward compatibility with django-cloudinary-storage under Django 6.0
STATICFILES_STORAGE = 'django.contrib.staticfiles.storage.StaticFilesStorage'



