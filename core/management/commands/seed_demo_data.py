"""
Management command: seed_demo_data
Creates realistic sample data across all AEC HR app modules.
Usage: python manage.py seed_demo_data
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import date, timedelta
import random


class Command(BaseCommand):
    help = 'Seeds the database with realistic demo data for all modules.'

    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.MIGRATE_HEADING('\n=== AEC HR Superapp — Demo Data Seeder ===\n'))
        self._seed_departments()
        self._seed_users()
        self._seed_profiles()
        self._seed_attendance()
        self._seed_leave()
        self.stdout.write(self.style.SUCCESS('\n✅ All demo data seeded successfully!\n'))

    # ── Departments ────────────────────────────────────────────
    def _seed_departments(self):
        from core.models import Department
        dept_names = [
            'AEC Cinemas', 'Bytes Caffe', 'AEC Residency',
            'AEC Studies Pvt Ltd', 'AEC Institute of Advanced Studies', 
            'AEC Pixel Perfect Pvt Ltd', 'AEC Enclave OPC Pvt Ltd',
            'AEC Travel and Leisure Solutions Pvt Limited'
        ]
        for name in dept_names:
            Department.objects.get_or_create(name=name)
        self.stdout.write(self.style.SUCCESS(f'  ✓ {len(dept_names)} Departments ready'))

    # ── Users ────────────────────────────────────────────────────
    def _seed_users(self):
        from core.models import User, Department
        depts = list(Department.objects.all())

        sample_staff = [
            ('Arjun', 'Nair', 'STAFF', 'arjun.nair', '9876543210'),
            ('Priya', 'Menon', 'STAFF', 'priya.menon', '9876543211'),
            ('Rohan', 'Das', 'DEPT_HEAD', 'rohan.das', '9876543212'),
            ('Sneha', 'Krishnan', 'STAFF', 'sneha.k', '9876543213'),
            ('Vivek', 'Pillai', 'STAFF', 'vivek.p', '9876543214'),
            ('Ananya', 'Thomas', 'DEPT_HEAD', 'ananya.t', '9876543215'),
            ('Kiran', 'Sharma', 'STAFF', 'kiran.s', '9876543216'),
            ('Meera', 'Nambiar', 'STAFF', 'meera.n', '9876543217'),
        ]

        created = 0
        for first, last, role, uname, phone in sample_staff:
            if not User.objects.filter(username=uname).exists():
                u = User.objects.create_user(
                    username=uname,
                    email=f'{uname}@aecgroup.in',
                    password='demo@1234',
                    first_name=first,
                    last_name=last,
                    role=role,
                    phone=phone,
                    is_active=True,
                )
                created += 1

        self.stdout.write(self.style.SUCCESS(f'  ✓ {created} new staff users created (password: demo@1234)'))

    # ── Employee Profiles ───────────────────────────────────────
    def _seed_profiles(self):
        from core.models import User, Department, EmployeeProfile

        depts = list(Department.objects.all())
        designations = ['Executive', 'Senior Executive', 'Manager', 'Team Lead', 'Analyst', 'Coordinator']
        probation_choices = ['PROBATION', 'PERMANENT']
        onboarding_choices = ['VERIFIED', 'VERIFIED', 'VERIFIED', 'REJECTED', 'PENDING']

        created = 0
        for user in User.objects.filter(role__in=['STAFF', 'DEPT_HEAD'], is_active=True):
            joining = date.today() - timedelta(days=random.randint(30, 730))
            prob_status = random.choice(probation_choices)
            onb_status = random.choice(onboarding_choices)
            dept = random.choice(depts)

            _, was_created = EmployeeProfile.objects.get_or_create(
                user=user,
                defaults={
                    'department': dept,
                    'designation': random.choice(designations),
                    'basic_salary': random.randint(15000, 60000),
                    'probation_status': prob_status,
                    'date_of_joining': joining,
                    'probation_end_date': joining + timedelta(days=90) if prob_status == 'PROBATION' else None,
                    'personal_account': f'SB{random.randint(100000000, 999999999)}',
                    'aadhaar_masked': 'XXXXXXXX' + str(random.randint(1000, 9999)),
                    'onboarding_status': onb_status,
                    'rejection_reason': 'Document Mismatch' if onb_status == 'REJECTED' else '',
                    'is_active': True,
                    'is_locked': True,
                    'docs_vault': {
                        'id_proof': {'url': '/media/demo/id_proof_sample.pdf', 'verified': True},
                        'academic_doc': {'url': '/media/demo/academic_sample.pdf', 'verified': True},
                    }
                }
            )
            if was_created:
                created += 1

        self.stdout.write(self.style.SUCCESS(f'  ✓ {created} Employee Profiles created'))

    # ── Attendance ───────────────────────────────────────────────
    def _seed_attendance(self):
        from core.models import EmployeeProfile, Attendance

        profiles = list(EmployeeProfile.objects.filter(is_active=True)[:5])
        created = 0
        today = date.today()

        for profile in profiles:
            for i in range(10):
                work_date = today - timedelta(days=i + 1)
                if work_date.weekday() < 5:  # Mon-Fri only
                    obj, was_created = Attendance.objects.get_or_create(
                        profile=profile,
                        date=work_date,
                        defaults={
                            'in_time': timezone.make_aware(
                                timezone.datetime.combine(work_date, timezone.datetime.strptime('09:00', '%H:%M').time())
                            ),
                            'out_time': timezone.make_aware(
                                timezone.datetime.combine(work_date, timezone.datetime.strptime('18:00', '%H:%M').time())
                            ),
                            'is_valid': True,
                            'source': 'MANUAL',
                        }
                    )
                    if was_created:
                        created += 1

        self.stdout.write(self.style.SUCCESS(f'  ✓ {created} Attendance records created'))

    # ── Leave Requests ───────────────────────────────────────────
    def _seed_leave(self):
        from core.models import EmployeeProfile, LeaveRequest, Holiday
        from django.apps import apps
        try:
            LeaveType = apps.get_model('core', 'LeaveType')
        except LookupError:
            LeaveType = None

        profiles = list(EmployeeProfile.objects.filter(is_active=True)[:4])
        statuses = ['APPROVED', 'PENDING', 'REJECTED']
        leave_types_choices = ['SICK', 'CASUAL', 'ANNUAL'] if LeaveType is None else None
        created = 0

        for i, profile in enumerate(profiles):
            start = date.today() - timedelta(days=random.randint(5, 30))
            end = start + timedelta(days=random.randint(1, 3))
            try:
                kwargs = {
                    'profile': profile,
                    'start_date': start,
                }
                defaults = {
                    'end_date': end,
                    'reason': 'Personal reasons',
                    'status': random.choice(statuses),
                    'leave_type': random.choice(['SICK', 'CASUAL', 'ANNUAL']),
                }
                obj, was_created = LeaveRequest.objects.get_or_create(**kwargs, defaults=defaults)
                if was_created:
                    created += 1
            except Exception as e:
                self.stdout.write(self.style.WARNING(f'  ⚠ Leave record error: {e}'))
                continue

        self.stdout.write(self.style.SUCCESS(f'  ✓ {created} Leave Requests created'))
