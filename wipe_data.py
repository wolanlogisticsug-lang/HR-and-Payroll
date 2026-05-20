import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'aec_hr_superapp.settings')
django.setup()

from django.apps import apps
from django.db import connection

# List of essential models we want to KEEP
KEEP_MODELS = [
    'core.Department',
    'core.Holiday',
    'auth.Group',
    'auth.Permission',
    'contenttypes.ContentType',
    'sessions.Session',
]

def wipe_data():
    models_to_clear = []
    for model in apps.get_models():
        app_label = model._meta.app_label
        model_name = model._meta.object_name
        full_name = f"{app_label}.{model_name}"
        
        if full_name not in KEEP_MODELS:
            models_to_clear.append(model)
            
    # We will just TRUNCATE all non-essential tables
    # Since it's PostgreSQL, we can use TRUNCATE CASCADE
    # Wait, the local env might be using PostgreSQL because of Neon DB!
    # Let's TRUNCATE CASCADE
    
    with connection.cursor() as cursor:
        for model in models_to_clear:
            if not model._meta.managed:
                continue
            table_name = model._meta.db_table
            print(f"Truncating {table_name}...")
            try:
                cursor.execute(f"TRUNCATE TABLE {table_name} CASCADE;")
            except Exception as e:
                print(f"Error truncating {table_name}: {e}")

wipe_data()
