import os
import sys
import django

# Add the project root to sys.path
sys.path.append('/Users/sethubibin/Desktop/HR_App')

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wolan Hr_hr_superapp.settings')
django.setup()

from core.models import User, EmployeeProfile
email = 'bibinbose2003@gmail.com'
users = User.objects.filter(email=email)
print(f"Users with email {email}:")
for u in users:
    print(f"- Username: {u.username}, PK: {u.pk}, Profile PK: {getattr(u, 'employee_profile', None).pk if hasattr(u, 'employee_profile') else 'None'}")

profiles = EmployeeProfile.objects.filter(user__email=email)
print(f"\nProfiles with user email {email}:")
for p in profiles:
    print(f"- Profile PK: {p.pk}, Employee ID: {p.employee_id}, Designation: {p.designation}")
