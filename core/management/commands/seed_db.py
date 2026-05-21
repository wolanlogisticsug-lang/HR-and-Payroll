import os
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from core.models import Department, EmployeeProfile
from decimal import Decimal

User = get_user_model()

class Command(BaseCommand):
    help = 'Seed database with initial departments and master users (MD, HR)'

    def handle(self, *args, **kwargs):
        self.stdout.write("Starting database seeding...")

        # 1. Create Departments (8 departments in Kochi)
        kochi_lat = Decimal('9.931233')
        kochi_lon = Decimal('76.267303')

        departments_data = [
            {'name': 'AEC Cinemas', 'code': 'CIN', 'is_cinema': True, 'work_days': '0,1,2,3,4,5,6'},
            {'name': 'Bytes Caffe', 'code': 'CAF', 'is_cinema': False, 'work_days': '0,1,2,3,4,5'},
            {'name': 'AEC Residency', 'code': 'RES', 'is_cinema': False, 'work_days': '0,1,2,3,4,5,6'},
            {'name': 'AEC Studies Pvt Ltd', 'code': 'EDU', 'is_cinema': False, 'work_days': '0,1,2,3,4,5'},
            {'name': 'AEC Institute of Advanced Studies', 'code': 'INS', 'is_cinema': False, 'work_days': '0,1,2,3,4,5'},
            {'name': 'AEC Pixel Perfect Pvt Ltd', 'code': 'PIX_IT', 'is_cinema': False, 'work_days': '0,1,2,3,4,5'},
            {'name': 'AEC Enclave OPC Pvt Ltd', 'code': 'ENCLAVE', 'is_cinema': False, 'work_days': '0,1,2,3,4,5'},
            {'name': 'AEC Travel and Leisure Solutions Pvt Limited', 'code': 'TLS', 'is_cinema': False, 'work_days': '0,1,2,3,4,5'},
        ]

        depts = {}
        for data in departments_data:
            dept, created = Department.objects.get_or_create(
                code=data['code'],
                defaults={
                    'name': data['name'],
                    'is_cinema': data['is_cinema'],
                    'work_days': data['work_days'],
                    'latitude': kochi_lat,
                    'longitude': kochi_lon,
                }
            )
            depts[data['code']] = dept
            if created:
                self.stdout.write(self.style.SUCCESS(f"Created department: {dept.name}"))

        # 2. Create MD User
        if not User.objects.filter(username='md_aec').exists():
            md_user = User.objects.create_superuser(
                username='md_aec',
                email='md@aecgroup.in',
                password='adminpassword123',
                first_name='Managing',
                last_name='Director'
            )
            md_user.role = User.Role.MD
            md_user.save()
            
            # Create MD Profile
            EmployeeProfile.objects.create(
                user=md_user,
                department=depts['ENCLAVE'],
                designation='Managing Director',
                probation_status=EmployeeProfile.ProbationStatus.PERMANENT,
                basic_salary=Decimal('100000.00'),
                is_locked=True
            )
            self.stdout.write(self.style.SUCCESS("Created MD User (md_aec / adminpassword123)"))

        # 3. Create HR User
        if not User.objects.filter(username='hr_aec').exists():
            hr_user = User.objects.create_user(
                username='hr_aec',
                email='hr@aecgroup.in',
                password='hrpassword123',
                first_name='HR',
                last_name='Manager'
            )
            hr_user.role = User.Role.HR
            hr_user.is_staff = True  # Can access admin
            hr_user.save()

            # Create HR Profile
            EmployeeProfile.objects.create(
                user=hr_user,
                department=depts['ENCLAVE'],
                designation='HR Manager',
                probation_status=EmployeeProfile.ProbationStatus.PERMANENT,
                basic_salary=Decimal('50000.00'),
                is_locked=True
            )
            self.stdout.write(self.style.SUCCESS("Created HR User (hr_aec / hrpassword123)"))

        self.stdout.write(self.style.SUCCESS("Database seeding completed successfully!"))
