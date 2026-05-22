from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from core.models import User, Department, EmployeeProfile

class MDOnboardingPermissionsTest(TestCase):
    def setUp(self):
        # Create users
        self.md_user = User.objects.create_user(
            username='md_user',
            password='testpassword',
            email='md@aec.com',
            role=User.Role.MD
        )
        self.hr_user = User.objects.create_user(
            username='hr_user',
            password='testpassword',
            email='hr@aec.com',
            role=User.Role.HR
        )
        self.staff_user = User.objects.create_user(
            username='staff_user',
            password='testpassword',
            email='staff@aec.com',
            role=User.Role.STAFF
        )

        # Create department
        self.dept = Department.objects.create(
            name='Engineering',
            code='ENG',
            is_active=True
        )

        # Create employee profiles
        self.md_profile = EmployeeProfile.objects.create(
            user=self.md_user,
            department=self.dept,
            probation_status=EmployeeProfile.ProbationStatus.PERMANENT,
            is_active=True
        )
        self.hr_profile = EmployeeProfile.objects.create(
            user=self.hr_user,
            department=self.dept,
            probation_status=EmployeeProfile.ProbationStatus.PERMANENT,
            is_active=True
        )
        self.staff_profile = EmployeeProfile.objects.create(
            user=self.staff_user,
            department=self.dept,
            probation_status=EmployeeProfile.ProbationStatus.PROBATION,
            is_active=True
        )

    def test_md_allowed_to_view_onboarding_dashboard(self):
        self.client.force_login(self.md_user)
        response = self.client.get(reverse('onboarding:onboarding_dashboard'))
        self.assertEqual(response.status_code, 200)

    def test_md_allowed_to_view_invite_candidate(self):
        self.client.force_login(self.md_user)
        response = self.client.get(reverse('onboarding:invite_candidate'))
        self.assertEqual(response.status_code, 200)

    def test_md_allowed_to_view_hr_verify_list(self):
        self.client.force_login(self.md_user)
        response = self.client.get(reverse('onboarding:hr_verify_list'))
        self.assertEqual(response.status_code, 200)

    def test_md_allowed_to_view_mail_center(self):
        self.client.force_login(self.md_user)
        response = self.client.get(reverse('onboarding:mail_center'))
        self.assertEqual(response.status_code, 200)

    def test_md_allowed_to_view_staff_directory(self):
        self.client.force_login(self.md_user)
        response = self.client.get(reverse('onboarding:staff_directory'))
        self.assertEqual(response.status_code, 200)

    def test_md_allowed_to_view_staff_detail(self):
        self.client.force_login(self.md_user)
        response = self.client.get(reverse('onboarding:staff_detail', args=[self.staff_profile.pk]))
        self.assertEqual(response.status_code, 200)

    def test_md_allowed_to_assign_manager(self):
        self.client.force_login(self.md_user)
        response = self.client.post(
            reverse('onboarding:assign_manager', args=[self.staff_profile.pk]),
            {'reporting_manager_id': self.hr_profile.pk}
        )
        self.assertRedirects(response, reverse('onboarding:staff_directory'))
        
        # Verify changes in DB
        self.staff_profile.refresh_from_db()
        self.assertEqual(self.staff_profile.reporting_manager, self.hr_profile)

    def test_md_allowed_to_delete_staff_profile(self):
        self.client.force_login(self.md_user)
        
        # Assert initial presence
        self.assertTrue(EmployeeProfile.objects.filter(pk=self.staff_profile.pk).exists())
        
        response = self.client.post(
            reverse('onboarding:delete_staff_profile', args=[self.staff_profile.pk]),
            {'confirm': 'yes'}
        )
        self.assertRedirects(response, reverse('onboarding:staff_directory'))
        
        # Verify deletion from DB
        self.assertFalse(EmployeeProfile.objects.filter(pk=self.staff_profile.pk).exists())

    def test_hr_allowed_to_access_onboarding_dashboard(self):
        self.client.force_login(self.hr_user)
        response = self.client.get(reverse('onboarding:onboarding_dashboard'))
        self.assertEqual(response.status_code, 200)
