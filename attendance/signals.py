"""
Attendance signal — late check + escalation.

Late escalation rule (per profile, per calendar month):
  1st late event   -> Attendance.is_late=True only
  2nd late event   -> + DisciplineRecord(severity=WARN) + email warn
  3rd late event   -> + DisciplineRecord(severity=DEDUCT_HALF_DAY, 0.5 days)
  4th+ late event  -> + DisciplineRecord(severity=DEDUCT_FULL_DAY, 1.0 days each)

Cinema departments are exempt — no late flag, no discipline record.
"""
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from core.models import Attendance


SHIFT_START_HOUR = 9
SHIFT_START_MIN = 30


def _process_late_check(attendance_id: int) -> None:
    """Worker: re-fetch, flag late, escalate discipline."""
    try:
        att = Attendance.objects.select_related('profile__department', 'profile__user').get(pk=attendance_id)
    except Attendance.DoesNotExist:
        return
    if not att.in_time:
        return
    if att.profile.department.is_cinema:
        return  # Cinema exempt

    local_in = timezone.localtime(att.in_time)
    shift_start_local = local_in.replace(
        hour=SHIFT_START_HOUR, minute=SHIFT_START_MIN, second=0, microsecond=0,
    )
    grace = timedelta(minutes=getattr(settings, 'GRACE_PERIOD_MINUTES', 15))

    if local_in <= (shift_start_local + grace):
        return  # Not late

    late_min = int((local_in - shift_start_local).total_seconds() / 60)
    Attendance.objects.filter(pk=att.pk).update(is_late=True, late_minutes=late_min)
    _escalate_discipline(att, late_min)


def _escalate_discipline(att, late_min):
    """Create DisciplineRecord based on month-to-date *late attendance count*
    (not existing record count, because 1st late never creates a record)."""
    from assets.models import DisciplineRecord
    from twofa.emails import send_html_mail

    profile = att.profile
    month_start = att.date.replace(day=1)

    # Avoid duplicates if signal fires twice for the same Attendance
    if DisciplineRecord.objects.filter(
        attendance=att, reason=DisciplineRecord.Reason.LATE_ESCALATION
    ).exists():
        return

    # Count late attendances in the month INCLUDING this one
    late_atts_qs = Attendance.objects.filter(
        profile=profile,
        date__gte=month_start,
        date__lt=_next_month(month_start),
        is_late=True,
    ).order_by('date', 'in_time')
    
    late_ids = list(late_atts_qs.values_list('id', flat=True))
    n = late_ids.index(att.id) + 1 if att.id in late_ids else late_atts_qs.count()

    severity = None
    deduction = Decimal('0')
    if n == 2:
        severity = DisciplineRecord.Severity.WARN
    elif n == 3:
        severity = DisciplineRecord.Severity.DEDUCT_HALF_DAY
        deduction = Decimal('0.5')
    elif n >= 4:
        severity = DisciplineRecord.Severity.DEDUCT_FULL_DAY
        deduction = Decimal('1.0')
    else:
        return  # 1st late, no record

    rec = DisciplineRecord.objects.create(
        profile=profile,
        attendance=att,
        occurred_on=att.date,
        reason=DisciplineRecord.Reason.LATE_ESCALATION,
        severity=severity,
        deduction_days=deduction,
        notes=f"Auto-generated. Late event #{n} this month. {late_min}m past shift start.",
    )

    # Email warning to employee + dept head
    recipients = []
    if profile.user.email:
        recipients.append(profile.user.email)
    if profile.department.head and profile.department.head.email:
        recipients.append(profile.department.head.email)
    
    if recipients:
        send_html_mail(
            subject=f"[AEC HR] Late attendance — {profile.user.get_full_name()} (#{n} this month)",
            template_name='email/late_warning.html',
            context={
                'profile': profile, 'attendance': att,
                'n': n, 'severity': rec.get_severity_display(),
                'late_min': late_min, 'deduction': deduction,
            },
            to=recipients,
        )

    # Also log as InternalMail so it appears in the app inbox
    from communications.models import InternalMail
    from core.models import User
    hr_user = User.objects.filter(role='HR', is_active=True).first()
    InternalMail.objects.create(
        sender=hr_user,
        recipient=profile.user,
        recipient_email=profile.user.email,
        subject=f"⚠️ Late Attendance Escalation #{n} this month",
        body=f"Dear {profile.user.first_name},\n\nYou clocked in {late_min} minutes after your shift start on {att.date}.\nThis is late event #{n} this month. Severity: {rec.get_severity_display()}.\nSalary Deduction: {deduction} day(s).\n\nPlease correct attendance immediately.",
        mail_type='LATE_WARNING',
    )


def _next_month(d):
    if d.month == 12:
        return d.replace(year=d.year + 1, month=1, day=1)
    return d.replace(month=d.month + 1, day=1)


@receiver(post_save, sender=Attendance)
def check_late_attendance(sender, instance, created, **kwargs):
    if instance.in_time is None:
        return
    # Skip if we are just updating the 'is_late' field itself (prevents infinite loop)
    if kwargs.get('update_fields') and 'is_late' in (kwargs.get('update_fields') or set()):
        return
    
    # Execute synchronously to ensure immediate update of late_minutes and discipline records
    _process_late_check(instance.pk)