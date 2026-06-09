import os
import sys
import django

# Add the project root to sys.path
sys.path.append('/Users/sethubibin/Desktop/HR_App')

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wolan Hr_hr_superapp.settings')
django.setup()

from core.models import User
for user in User.objects.all():
    print(f"User: {user.username}, Photo: {user.profile_picture}")
