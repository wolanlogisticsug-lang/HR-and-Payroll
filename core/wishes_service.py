from datetime import date
from django.utils import timezone
from core.models import EmployeeProfile, User
from notifications.models import Notification
from communications.models import InternalMail

def get_name(u):
    full = u.get_full_name().strip()
    if full:
        return full
    if u.first_name:
        return u.first_name.strip()
    return u.username

def ensure_daily_wishes_and_alerts():
    today = timezone.now().date()
    
    # Get HR user to act as sender of automated mails
    hr_user = User.objects.filter(role='HR', is_active=True).first()
    if not hr_user:
        hr_user = User.objects.filter(is_superuser=True).first()
        
    profiles = EmployeeProfile.objects.filter(is_active=True, probation_status__in=[EmployeeProfile.ProbationStatus.PROBATION, EmployeeProfile.ProbationStatus.PERMANENT]).select_related('user', 'department')
    
    for profile in profiles:
        u = profile.user
        name = get_name(u)
        fname = u.first_name or name
        # 1. Birthday Wish & Notification
        if u.date_of_birth and u.date_of_birth.month == today.month and u.date_of_birth.day == today.day:
            title = f"🎉 Today is {name}'s Birthday!"
            msg = f"Join us in wishing {name} ({profile.designation or 'Staff'}) a fantastic birthday and a wonderful year ahead!"
            
            # Create Notification for all staff if not exists
            if not Notification.objects.filter(target_profile=profile, notification_type='BIRTHDAY_WISH', created_at__date=today).exists():
                Notification.objects.create(
                    title=title,
                    message=msg,
                    created_by=hr_user,
                    notification_type='BIRTHDAY_WISH',
                    target_profile=profile,
                )
            
            # Send InternalMail wish to employee
            if hr_user and not InternalMail.objects.filter(recipient=u, mail_type='WISH', created_at__date=today, subject__icontains='Birthday').exists():
                InternalMail.objects.create(
                    sender=hr_user,
                    recipient=u,
                    subject=f"🎂 Happy Birthday, {name}!",
                    body=f"Dear {fname},\n\nWishing you a very Happy Birthday! May your day be filled with joy and celebration.\n\nBest Wishes,\nAEC HR Team",
                    mail_type='WISH',
                )
                
        # 2. Wedding Anniversary Wish & Notification
        if profile.wedding_anniversary and profile.wedding_anniversary.month == today.month and profile.wedding_anniversary.day == today.day:
            title = f"💍 Today is {name}'s Wedding Anniversary!"
            spouse_part = f" and their spouse {profile.spouse_name}" if profile.spouse_name else ""
            msg = f"Join us in wishing {name}{spouse_part} a very happy wedding anniversary! Wishing them many more years of love and happiness."
            
            if not Notification.objects.filter(target_profile=profile, notification_type='ANNIVERSARY_WISH', created_at__date=today).exists():
                Notification.objects.create(
                    title=title,
                    message=msg,
                    created_by=hr_user,
                    notification_type='ANNIVERSARY_WISH',
                    target_profile=profile,
                )
                
            if hr_user and not InternalMail.objects.filter(recipient=u, mail_type='WISH', created_at__date=today, subject__icontains='Anniversary').exists():
                InternalMail.objects.create(
                    sender=hr_user,
                    recipient=u,
                    subject=f"💐 Happy Wedding Anniversary, {name}!",
                    body=f"Dear {fname},\n\nWishing you{spouse_part} a joyous wedding anniversary filled with wonderful memories.\n\nBest Regards,\nAEC HR Team",
                    mail_type='WISH',
                )

def trigger_onboarding_wish(profile):
    hr_user = User.objects.filter(role='HR', is_active=True).first()
    if not hr_user:
        hr_user = User.objects.filter(is_superuser=True).first()
    u = profile.user
    name = get_name(u)
    fname = u.first_name or name
    title = f"👋 Welcome Our New Colleague: {name}!"
    dept_name = profile.department.name if profile.department else "General"
    msg = f"We are thrilled to welcome {name} to the AEC Group as {profile.designation or 'Staff'} in the {dept_name} department! Please give them a warm welcome."
    
    if not Notification.objects.filter(target_profile=profile, notification_type='ONBOARDING_WISH').exists():
        Notification.objects.create(
            title=title,
            message=msg,
            created_by=hr_user,
            notification_type='ONBOARDING_WISH',
            target_profile=profile,
        )
        
    if hr_user and not InternalMail.objects.filter(recipient=u, mail_type='WISH', subject__icontains='Welcome').exists():
        InternalMail.objects.create(
            sender=hr_user,
            recipient=u,
            subject=f"🌟 Welcome to AEC Group, {name}!",
            body=f"Dear {fname},\n\nWelcome aboard! We are excited to have you join our team. We wish you a successful and rewarding career with us.\n\nWarm Regards,\nAEC HR Team",
            mail_type='WISH',
        )

def trigger_promotion_wish(profile, new_designation):
    hr_user = User.objects.filter(role='HR', is_active=True).first()
    if not hr_user:
        hr_user = User.objects.filter(is_superuser=True).first()
    u = profile.user
    name = get_name(u)
    fname = u.first_name or name
    title = f"🚀 Congratulations to {name} on their Promotion!"
    dept_name = profile.department.name if profile.department else "General"
    msg = f"We are delighted to announce that {name} has been promoted to {new_designation} in the {dept_name} department! Join us in congratulating them on this milestone."
    
    Notification.objects.create(
        title=title,
        message=msg,
        created_by=hr_user,
        notification_type='PROMOTION_WISH',
        target_profile=profile,
    )
    
    if hr_user:
        InternalMail.objects.create(
            sender=hr_user,
            recipient=u,
            subject=f"🎉 Congratulations on your Promotion, {name}!",
            body=f"Dear {fname},\n\nCongratulations on your well-deserved promotion to {new_designation}! Your dedication and hard work are highly appreciated.\n\nBest Regards,\nAEC HR Team",
            mail_type='WISH',
        )
