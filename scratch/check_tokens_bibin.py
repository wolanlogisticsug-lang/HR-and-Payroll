import os
import sys
import django

# Add the project root to sys.path
sys.path.append('/Users/sethubibin/Desktop/HR_App')

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wolan Hr_hr_superapp.settings')
django.setup()

from onboarding.models import InviteToken
tokens = InviteToken.objects.filter(email='bibinbose2003@gmail.com')
for t in tokens:
    print(f"Token: {t.id}, Used: {t.is_used}, Profile: {t.profile}")
