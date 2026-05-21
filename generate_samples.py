import os
import django
from datetime import date, timedelta
import random

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'aec_hr_superapp.settings')
django.setup()

from core.models import User, Department, EmployeeProfile, Attendance

# Get all departments
departments = Department.objects.filter(is_active=True)
if not departments.exists():
    departments = [Department.objects.create(name='General', code='GEN', is_active=True)]

def generate_samples():
    joining_date = date.today() - timedelta(days=30)
    
    for dept in departments:
        # Generate 12 employees per department
        for i in range(1, 13):
            username = f'emp_{dept.code.lower()}_{i}'
            if User.objects.filter(username=username).exists():
                continue
                
            first_name = f'{dept.name}'
            last_name = f'Staff {i}'
            
            user = User.objects.create_user(
                username=username,
                password='password123',
                first_name=first_name,
                last_name=last_name,
                role='STAFF'
            )
            
            # Randomly distribute statuses
            probation_status = EmployeeProfile.ProbationStatus.PERMANENT if i > 4 else EmployeeProfile.ProbationStatus.PROBATION
            is_active = True
            
            # Make the last 2 terminated
            if i >= 11:
                is_active = False
            
            import uuid
            profile = EmployeeProfile(
                user=user,
                department=dept,
                designation=f'{dept.name} Associate',
                basic_salary=random.randint(15000, 35000),
                probation_status=probation_status,
                is_active=is_active,
                onboarding_status='COMPLETED',
                date_of_joining=joining_date,
            )
            profile.employee_id = f"AEC-{dept.code}-{uuid.uuid4().hex[:6].upper()}"
            profile.save()
            
            # Only create attendance for active employees to test payroll
            if is_active:
                # We will mark them present for the last 30 days randomly, mostly present
                for day_offset in range(30):
                    current_date = joining_date + timedelta(days=day_offset)
                    # Skip sundays
                    if current_date.weekday() == 6:
                        continue
                        
                    if random.random() < 0.90:
                        from datetime import datetime
                        in_dt = datetime.combine(current_date, datetime.strptime("09:00:00", "%H:%M:%S").time())
                        out_dt = datetime.combine(current_date, datetime.strptime("17:00:00", "%H:%M:%S").time())
                        Attendance.objects.create(
                            profile=profile,
                            date=current_date,
                            in_time=in_dt,
                            out_time=out_dt,
                            is_valid=True,
                            location_name="AEC Group"
                        )

if __name__ == '__main__':
    generate_samples()
    print("Sample generation complete.")
