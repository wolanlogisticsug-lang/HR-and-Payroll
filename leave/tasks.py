"""
Background tasks scheduled via django-q2.

- holiday_fetch_kerala: ensure Kerala public holidays exist for current year.
- birthday_sms: daily — SMS via Twilio stub for birthdays today.
- anniversary_sms: daily — SMS for joining anniversaries today.
"""
import logging
from datetime import date

from core.models import EmployeeProfile, Holiday

logger = logging.getLogger(__name__)


# Hardcoded Kerala 2026 holiday seed (replace with API call to a real
# Kerala govt feed in prod).
KERALA_2026 = [
    ('Republic Day', date(2026, 1, 26)),
    ('Maha Shivaratri', date(2026, 2, 17)),
    ('Holi', date(2026, 3, 4)),
    ('Eid-ul-Fitr', date(2026, 3, 21)),
    ('Vishu', date(2026, 4, 14)),
    ('Good Friday', date(2026, 4, 3)),
    ('May Day', date(2026, 5, 1)),
    ('Eid-ul-Adha', date(2026, 5, 28)),
    ('Independence Day', date(2026, 8, 15)),
    ('Onam', date(2026, 8, 28)),
    ('Thiruvonam', date(2026, 8, 29)),
    ('Mahanavami', date(2026, 10, 19)),
    ('Vijaya Dashami', date(2026, 10, 20)),
    ('Diwali', date(2026, 11, 8)),
    ('Christmas', date(2026, 12, 25)),
]


def holiday_fetch_kerala(year: int = None):
    """Idempotent — ensures Kerala public holidays for year exist as
    Holiday rows. HR can deactivate via the holidays page."""
    year = year or date.today().year
    seed = KERALA_2026 if year == 2026 else []  # extend as needed
    created = 0
    for name, dt in seed:
        _, was_created = Holiday.objects.get_or_create(
            name=name, date=dt,
            defaults={'is_public': True, 'is_active': True},
        )
        if was_created:
            created += 1
    logger.info("holiday_fetch_kerala(%s): %s new", year, created)
    return created


def _twilio_send_sms_stub(to: str, body: str):
    """Twilio stub. In production, replace with actual Twilio integration:
        from twilio.rest import Client
        Client(sid, auth).messages.create(to=to, from_=settings.TWILIO_FROM, body=body)
    For now it just logs to qcluster output."""
    logger.info("[Twilio STUB] -> %s : %s", to, body)


def birthday_sms():
    """Run daily — send birthday wishes to staff whose DoB matches today."""
    today = date.today()
    qs = EmployeeProfile.objects.filter(
        is_active=True,
        probation_status__in=['PROBATION', 'PERMANENT'],
        user__date_of_birth__month=today.month,
        user__date_of_birth__day=today.day,
    ).select_related('user')
    sent = 0
    for p in qs:
        if p.user.phone:
            _twilio_send_sms_stub(
                p.user.phone,
                f"Dear {p.user.first_name}, AEC Group wishes you a very happy birthday! 🎉",
            )
            sent += 1
    logger.info("birthday_sms: %s SMS sent", sent)
    return sent


def anniversary_sms():
    """Run daily — send anniversary message for joining-day match (>=1 year)."""
    today = date.today()
    qs = EmployeeProfile.objects.filter(
        is_active=True,
        probation_status__in=['PROBATION', 'PERMANENT'],
        date_of_joining__month=today.month,
        date_of_joining__day=today.day,
    ).exclude(date_of_joining__year=today.year).select_related('user')
    sent = 0
    for p in qs:
        if p.user.phone:
            years = today.year - p.date_of_joining.year
            _twilio_send_sms_stub(
                p.user.phone,
                f"Congratulations on completing {years} year(s) at AEC Group, {p.user.first_name}!",
            )
            sent += 1
    logger.info("anniversary_sms: %s SMS sent", sent)
    return sent
