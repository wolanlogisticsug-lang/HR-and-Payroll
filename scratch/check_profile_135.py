import os
import sys
import django

# Add the project root to sys.path
sys.path.append('/Users/sethubibin/Desktop/HR_App')

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wolan Hr_hr_superapp.settings')
django.setup()

from core.models import User, EmployeeProfile
try:
    profile = EmployeeProfile.objects.select_related('user').get(pk=135)
    print(f"Profile ID: {profile.pk}")
    print(f"User: {profile.user.username}, Email: {profile.user.email}")
    print(f"Designation: {profile.designation}")
    print(f"Joined: {profile.date_of_joining}")
    print(f"Photo: {profile.user.profile_picture}")
    print(f"Vault: {profile.docs_vault}")
except EmployeeProfile.DoesNotExist:
    print("Profile 135 not found")
except Exception as e:
    print(f"Error: {e}")
