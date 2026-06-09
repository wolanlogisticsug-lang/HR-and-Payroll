import os
import sys
import django

# Add the project root to sys.path
sys.path.append('/Users/sethubibin/Desktop/HR_App')

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wolan Hr_hr_superapp.settings')
django.setup()

from core.models import User
u = User.objects.get(username='bibin')
print(f"Username: {u.username}")
print(f"Email: {u.email}")
print(f"First Name: {u.first_name}")
print(f"Last Name: {u.last_name}")
print(f"Role: {u.role}")
print(f"Active: {u.is_active}")
