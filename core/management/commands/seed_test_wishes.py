from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import date, timedelta
from core.models import User, Department, EmployeeProfile, Attendance
from notifications.models import Notification
from communications.models import InternalMail
from assets.models import DisciplineRecord
from decimal import Decimal

class Command(BaseCommand):
    help = 'Seeds sample test data to verify automated wishes, announcements, and late warnings.'

    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.MIGRATE_HEADING('\n=== wolan Hr HR Superapp — Wishes & Warnings Seeder ===\n'))
        
        # Clear old wish notifications to ensure fresh names
        Notification.objects.filter(notification_type__in=['BIRTHDAY_WISH', 'ANNIVERSARY_WISH', 'ONBOARDING_WISH', 'PROMOTION_WISH']).delete()

        today = timezone.now().date()
        hr_user = User.objects.filter(role='HR', is_active=True).first()
        if not hr_user:
            hr_user = User.objects.filter(is_superuser=True).first()
            
        staff_users = list(User.objects.filter(is_active=True).exclude(role='MD').order_by('id'))
        if len(staff_users) < 5:
            for i in range(5):
                u, _ = User.objects.get_or_create(username=f'staff_demo_{i}', defaults={
                    'email': f'staff_{i}@wolan Hrgroup.in',
                    'first_name': f'DemoStaff{i}',
                    'last_name': 'wolan Hr',
                    'role': 'STAFF',
                    'is_active': True,
                })
                dept, _ = Department.objects.get_or_create(name='wolan Hr Cinemas')
                EmployeeProfile.objects.get_or_create(user=u, defaults={
                    'department': dept,
                    'designation': 'Executive',
                    'basic_salary': Decimal('25000'),
                    'is_active': True,
                })
                if u not in staff_users:
                    staff_users.append(u)

        names_data = [
            ("Priya", "Menon"),
            ("Arjun", "Nair"),
            ("Sneha", "Krishnan"),
            ("Vivek", "Pillai"),
            ("Kiran", "Sharma"),
        ]
        for idx, (fn, ln) in enumerate(names_data):
            if idx < len(staff_users):
                u = staff_users[idx]
                if not u.first_name:
                    u.first_name = fn
                    u.last_name = ln
                    u.save()
                    
        # 1. Birthday User
        u1 = staff_users[0]
        u1.date_of_birth = today.replace(year=today.year - 28)
        u1.save()
        p1 = getattr(u1, 'employee_profile', None)
        if p1:
            p1.hobbies = "Reading, Classical Dancing"
            p1.save()
            
        # 2. Anniversary User
        u2 = staff_users[1]
        p2 = getattr(u2, 'employee_profile', None)
        if p2:
            p2.wedding_anniversary = today.replace(year=today.year - 5)
            p2.spouse_name = "Lakshmi Nair"
            p2.hobbies = "Photography, Traveling"
            p2.save()
            
        # Trigger daily check
        from core.wishes_service import ensure_daily_wishes_and_alerts
        ensure_daily_wishes_and_alerts()
        self.stdout.write(self.style.SUCCESS(f'  ✓ Birthday wish generated for {u1.get_full_name()}.'))
        self.stdout.write(self.style.SUCCESS(f'  ✓ Wedding Anniversary wish generated for {u2.get_full_name()}.'))
        
        # 3. Onboarding Wish User
        u3 = staff_users[2]
        if hasattr(u3, 'employee_profile'):
            from core.wishes_service import trigger_onboarding_wish
            trigger_onboarding_wish(u3.employee_profile)
            self.stdout.write(self.style.SUCCESS(f'  ✓ Onboarding wish generated for {u3.get_full_name()}.'))
            
        # 4. Promotion Wish User
        u4 = staff_users[3]
        if hasattr(u4, 'employee_profile'):
            from core.wishes_service import trigger_promotion_wish
            trigger_promotion_wish(u4.employee_profile, "Senior Data Scientist")
            self.stdout.write(self.style.SUCCESS(f'  ✓ Promotion wish generated for {u4.get_full_name()}.'))
            
        # 5. Late coming warning message
        u5 = staff_users[4]
        if hasattr(u5, 'employee_profile'):
            p5 = u5.employee_profile
            att1, _ = Attendance.objects.get_or_create(
                profile=p5,
                date=today - timedelta(days=2),
                defaults={
                    'in_time': timezone.make_aware(timezone.datetime.combine(today - timedelta(days=2), timezone.datetime.strptime('09:45', '%H:%M').time())),
                    'out_time': timezone.make_aware(timezone.datetime.combine(today - timedelta(days=2), timezone.datetime.strptime('18:00', '%H:%M').time())),
                    'is_late': True,
                    'late_minutes': 45,
                }
            )
            att2, _ = Attendance.objects.get_or_create(
                profile=p5,
                date=today - timedelta(days=1),
                defaults={
                    'in_time': timezone.make_aware(timezone.datetime.combine(today - timedelta(days=1), timezone.datetime.strptime('09:30', '%H:%M').time())),
                    'out_time': timezone.make_aware(timezone.datetime.combine(today - timedelta(days=1), timezone.datetime.strptime('18:00', '%H:%M').time())),
                    'is_late': True,
                    'late_minutes': 30,
                }
            )
            
            if not InternalMail.objects.filter(recipient=u5, mail_type='LATE_WARNING').exists():
                InternalMail.objects.create(
                    sender=hr_user,
                    recipient=u5,
                    recipient_email=u5.email,
                    subject="⚠️ Late Attendance Escalation #2 this month",
                    body=f"Dear {u5.first_name},\n\nYou clocked in 30 minutes after your shift start on {att2.date}.\nThis is late event #2 this month. Severity: Warning.\nSalary Deduction: 0 day(s).\n\nPlease correct attendance immediately.",
                    mail_type='LATE_WARNING',
                )
            self.stdout.write(self.style.SUCCESS(f'  ✓ Late attendance warning message generated for {u5.get_full_name()}.'))
            
        self.stdout.write(self.style.SUCCESS('\n✅ All sample test data for wishes and late warnings seeded successfully!\n'))
