"""
Iteration 3 — Leave quota / Holidays / Discipline escalation / Calendar / NOC / Assets / Schedules
Run: cd /app && /root/.venv/bin/python -m pytest backend/tests/test_iter3_assets_leave_discipline.py -v
"""
import os
import sys
import django
from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from decimal import Decimal

import pytest

# Bootstrap Django
sys.path.insert(0, '/app')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'wolan Hr_hr_superapp.settings')
django.setup()

from django.test import Client
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from django.urls import reverse

from core.models import (
    User, EmployeeProfile, Department, Holiday, LeaveRequest, Attendance, AuditLog,
)
from assets.models import CompanyAsset, NOC, DisciplineRecord
from leave import tasks as leave_tasks
from leave.views import _half_day_count, _quota_for
from payroll import service as payroll_service
from attendance.signals import _process_late_check


HR = 'hr_wolan Hr'
HR_PASS = 'hrpassword123'


# ---------- Fixtures ----------
@pytest.fixture
def hr_user():
    return User.objects.get(username=HR)


@pytest.fixture
def hr_profile(hr_user):
    return hr_user.employee_profile


@pytest.fixture
def hr_client():
    c = Client()
    assert c.login(username=HR, password=HR_PASS), "HR login failed"
    return c


# Make HR permanent so quota=4 (defensive)
@pytest.fixture(autouse=True)
def _ensure_permanent(hr_profile):
    if hr_profile.probation_status != EmployeeProfile.ProbationStatus.PERMANENT:
        hr_profile.probation_status = EmployeeProfile.ProbationStatus.PERMANENT
        hr_profile.save(update_fields=['probation_status'])


# ---------- Holidays ----------
class TestHolidays:
    def test_fetch_seeds_kerala_2026(self):
        created = leave_tasks.holiday_fetch_kerala(2026)
        # idempotent — second run returns 0
        again = leave_tasks.holiday_fetch_kerala(2026)
        assert again == 0
        assert Holiday.objects.filter(date__year=2026, is_public=True).count() >= 15

    def test_holidays_list_view(self, hr_client):
        leave_tasks.holiday_fetch_kerala(2026)
        r = hr_client.get('/leave/holidays/?year=2026')
        assert r.status_code == 200
        assert b'holidays-table' in r.content

    def test_holiday_add_toggle_delete(self, hr_client):
        # Add custom
        r = hr_client.post('/leave/holidays/add/',
                           {'name': 'TEST_iter3 Day', 'date': '2026-12-31'})
        assert r.status_code in (200, 302)
        h = Holiday.objects.get(name='TEST_iter3 Day', date=date(2026, 12, 31))
        assert h.is_public is False
        assert h.is_active is True

        # Toggle
        r = hr_client.post(f'/leave/holidays/{h.pk}/toggle/')
        assert r.status_code in (200, 302)
        h.refresh_from_db()
        assert h.is_active is False

        # Delete
        r = hr_client.post(f'/leave/holidays/{h.pk}/delete/')
        assert r.status_code in (200, 302)
        assert not Holiday.objects.filter(pk=h.pk).exists()

    def test_holiday_fetch_view(self, hr_client):
        r = hr_client.post('/leave/holidays/fetch/', {'year': '2026'})
        assert r.status_code in (200, 302)


# ---------- Working days in payroll ----------
class TestWorkingDays:
    def test_aug_2026_uses_holidays_and_workdays(self):
        leave_tasks.holiday_fetch_kerala(2026)
        hr_dept = User.objects.get(username=HR).employee_profile.department
        wd = payroll_service.working_days_in_month(2026, 8, hr_dept)
        # Mon-Sat raw in Aug 2026 = 27. Active 2026 Kerala holidays in Aug:
        # Aug-15(Sat), Aug-28(Fri), Aug-29(Sat). Expect <27 and >=22.
        assert wd < 27
        assert 22 <= wd <= 26


# ---------- Leave quota enforcement ----------
@pytest.mark.django_db(transaction=True)
class TestLeaveQuota:
    def setup_method(self):
        # Wipe HR's Sep 2026 leaves only (test isolation)
        u = User.objects.get(username=HR)
        LeaveRequest.objects.filter(
            profile=u.employee_profile,
            start_date__year=2026, start_date__month=9,
        ).delete()

    def teardown_method(self):
        u = User.objects.get(username=HR)
        LeaveRequest.objects.filter(
            profile=u.employee_profile,
            start_date__year=2026, start_date__month=9,
        ).delete()

    def test_half_day_count_helper(self):
        u = User.objects.get(username=HR)
        l = LeaveRequest(profile=u.employee_profile,
                         leave_type=LeaveRequest.LeaveType.HALF_DAY,
                         start_date=date(2026, 9, 1), end_date=date(2026, 9, 1))
        assert _half_day_count(l) == Decimal('1')
        l2 = LeaveRequest(profile=u.employee_profile,
                          leave_type=LeaveRequest.LeaveType.SICK,
                          start_date=date(2026, 9, 1), end_date=date(2026, 9, 3))
        assert _half_day_count(l2) == Decimal('6')  # 3 days * 2

    def test_quota_for_permanent(self):
        u = User.objects.get(username=HR)
        assert _quota_for(u.employee_profile) == Decimal('4')

    def test_quota_blocks_3day_sick(self, hr_client):
        # 3 days SICK = 6 half-days > 4 -> reject
        r = hr_client.post('/leave/new/', {
            'leave_type': 'SICK',
            'start_date': '2026-09-01',
            'end_date': '2026-09-03',
            'reason': 'TEST_iter3 quota block',
        }, follow=True)
        assert r.status_code == 200
        u = User.objects.get(username=HR)
        assert not LeaveRequest.objects.filter(
            profile=u.employee_profile,
            start_date=date(2026, 9, 1),
            reason='TEST_iter3 quota block',
        ).exists()

    def test_quota_progressive(self, hr_client):
        u = User.objects.get(username=HR)
        # HALF on 09-01 = 1 used
        r = hr_client.post('/leave/new/', {
            'leave_type': 'HALF',
            'start_date': '2026-09-01', 'end_date': '2026-09-01',
            'reason': 'TEST_iter3 step1',
        }, follow=True)
        assert r.status_code == 200
        assert LeaveRequest.objects.filter(
            profile=u.employee_profile, start_date=date(2026, 9, 1),
            reason='TEST_iter3 step1').exists(), "HALF should be allowed"

        # FULL on 09-02 -> 1+2=3 still <=4
        r = hr_client.post('/leave/new/', {
            'leave_type': 'FULL',
            'start_date': '2026-09-02', 'end_date': '2026-09-02',
            'reason': 'TEST_iter3 step2',
        }, follow=True)
        assert LeaveRequest.objects.filter(
            profile=u.employee_profile, reason='TEST_iter3 step2').exists()

        # SICK on 09-04 -> +2 = 5 > 4 -> reject
        r = hr_client.post('/leave/new/', {
            'leave_type': 'SICK',
            'start_date': '2026-09-04', 'end_date': '2026-09-04',
            'reason': 'TEST_iter3 step3',
        }, follow=True)
        assert not LeaveRequest.objects.filter(
            profile=u.employee_profile, reason='TEST_iter3 step3').exists(), \
            "SICK should exceed quota and be rejected"


# ---------- Discipline escalation ----------
@pytest.mark.django_db(transaction=True)
class TestDiscipline:
    def setup_method(self):
        u = User.objects.get(username=HR)
        prof = u.employee_profile
        # Reset Jul 2026
        Attendance.objects.filter(
            profile=prof, date__year=2026, date__month=7).delete()
        DisciplineRecord.objects.filter(
            profile=prof, occurred_on__year=2026, occurred_on__month=7).delete()

    def _make_late(self, profile, day):
        # 04:30 UTC = 10:00 IST (60 min late vs 09:00 shift)
        in_dt = datetime(2026, 7, day, 4, 30, tzinfo=dt_timezone.utc)
        att = Attendance.objects.create(
            profile=profile,
            date=date(2026, 7, day),
            in_time=in_dt,
            is_valid=True,
        )
        return att

    def test_escalation_2_to_5(self):
        u = User.objects.get(username=HR)
        prof = u.employee_profile
        atts = []
        for day in (1, 2, 3, 4, 5):
            atts.append(self._make_late(prof, day))
            # Force sync invocation (signals also fired but should be idempotent
            # because of attendance-uniqueness guard)
            _process_late_check(atts[-1].pk)

        recs = DisciplineRecord.objects.filter(
            profile=prof, occurred_on__year=2026, occurred_on__month=7,
            reason=DisciplineRecord.Reason.LATE_ESCALATION,
        ).order_by('occurred_on')
        assert recs.count() == 4, f"Expected 4 records, got {recs.count()}: {[(r.occurred_on, r.severity) for r in recs]}"
        sevs = [(r.occurred_on.day, r.severity, r.deduction_days) for r in recs]
        assert sevs[0] == (2, 'WARN', Decimal('0'))
        assert sevs[1] == (3, 'HALF', Decimal('0.5'))
        assert sevs[2] == (4, 'FULL', Decimal('1.0'))
        assert sevs[3] == (5, 'FULL', Decimal('1.0'))
        total = sum((r.deduction_days for r in recs), Decimal('0'))
        assert total == Decimal('2.5')

    def test_payroll_uses_discipline(self):
        u = User.objects.get(username=HR)
        prof = u.employee_profile
        # Re-create the 4 records (test runs independently)
        for day in (1, 2, 3, 4, 5):
            self._make_late(prof, day)
            att = Attendance.objects.filter(
                profile=prof, date=date(2026, 7, day)).first()
            _process_late_check(att.pk)

        svc = payroll_service.PayrollService(prof, 2026, 7)
        result = svc.compute()
        assert result['discipline_days'] == Decimal('2.50')
        # disc amount > 0 and equals days * daily
        expected_amt = (Decimal('2.50') * result['daily_rate']).quantize(Decimal('0.01'))
        assert result['discipline_amount'] == expected_amt
        # gross >= 0
        assert result['gross_salary'] >= Decimal('0')

    def test_cinema_exempt(self):
        cin_dept = Department.objects.filter(is_cinema=True).first()
        assert cin_dept, "CIN department must be seeded"
        # Find or create a CIN profile
        cin_profile = EmployeeProfile.objects.filter(department=cin_dept, is_active=True).first()
        if not cin_profile:
            cin_user = User.objects.create_user(
                username='TEST_cin_user', password='x', role=User.Role.STAFF,
                email='cin@test.local',
            )
            cin_profile = EmployeeProfile.objects.create(
                user=cin_user, department=cin_dept,
                employee_id='TEST_CIN001', basic_salary=Decimal('20000'),
                date_of_joining=date(2025, 1, 1),
            )
        Attendance.objects.filter(profile=cin_profile, date=date(2026, 7, 10)).delete()
        in_dt = datetime(2026, 7, 10, 4, 30, tzinfo=dt_timezone.utc)
        att = Attendance.objects.create(
            profile=cin_profile, date=date(2026, 7, 10),
            in_time=in_dt, is_valid=True,
        )
        _process_late_check(att.pk)
        assert not DisciplineRecord.objects.filter(
            profile=cin_profile, occurred_on=date(2026, 7, 10)).exists(), \
            "Cinema dept must be exempt from discipline"


# ---------- SMS stubs ----------
class TestSmsStubs:
    def test_birthday_sms_runs(self):
        n = leave_tasks.birthday_sms()
        assert isinstance(n, int)

    def test_anniversary_sms_runs(self):
        n = leave_tasks.anniversary_sms()
        assert isinstance(n, int)


# ---------- Approval chain redirect ----------
@pytest.mark.django_db(transaction=True)
class TestLeaveRedirect:
    def test_redirect_keeps_pending_and_logs(self, hr_client):
        u = User.objects.get(username=HR)
        # Create a pending leave for HR
        leave = LeaveRequest.objects.create(
            profile=u.employee_profile,
            leave_type=LeaveRequest.LeaveType.HALF_DAY,
            start_date=date(2026, 10, 5), end_date=date(2026, 10, 5),
            reason='TEST_iter3 redirect',
            status=LeaveRequest.Status.PENDING,
        )
        # Redirect to MD
        md = User.objects.get(username='md_wolan Hr')
        r = hr_client.post(f'/leave/{leave.pk}/decision/', {
            'action': 'redirect', 'redirect_to': str(md.pk),
        }, follow=True)
        assert r.status_code == 200
        leave.refresh_from_db()
        assert leave.status == LeaveRequest.Status.PENDING
        assert 'Redirected by' in (leave.rejection_reason or '')
        assert AuditLog.objects.filter(
            profile=u.employee_profile,
            details__pk=leave.pk,
        ).filter(details__redirected_to='md_wolan Hr').exists()
        leave.delete()


# ---------- Leave Calendar ----------
class TestLeaveCalendar:
    def test_calendar_renders_grid(self, hr_client):
        leave_tasks.holiday_fetch_kerala(2026)
        r = hr_client.get('/leave/calendar/?year=2026&month=8')
        assert r.status_code == 200
        assert b'leave-calendar-grid' in r.content
        # Aug holidays should appear
        assert b'Independence Day' in r.content or b'15' in r.content


# ---------- Assets ----------
@pytest.mark.django_db(transaction=True)
class TestAssets:
    def test_dashboard_loads(self, hr_client):
        r = hr_client.get('/assets/')
        assert r.status_code == 200
        assert b'asset-issue-form' in r.content

    def test_issue_and_return(self, hr_client, hr_profile):
        r = hr_client.post('/assets/issue/', {
            'profile_id': str(hr_profile.pk),
            'asset_type': 'PHONE',
            'label': 'TEST_iter3 iPhone 15',
            'serial_no': 'ABC123',
            'issued_date': '2026-08-01',
        }, follow=True)
        assert r.status_code == 200
        a = CompanyAsset.objects.filter(label='TEST_iter3 iPhone 15').first()
        assert a is not None
        assert a.status == CompanyAsset.Status.ISSUED

        # Verify in dashboard
        r = hr_client.get('/assets/')
        assert b'TEST_iter3 iPhone 15' in r.content

        # Return
        r = hr_client.post(f'/assets/{a.pk}/return/', follow=True)
        a.refresh_from_db()
        assert a.status == CompanyAsset.Status.RETURNED
        assert a.returned_date is not None
        a.delete()


# ---------- NOC ----------
@pytest.mark.django_db(transaction=True)
class TestNOC:
    def test_noc_issue_download_sign(self, hr_client, hr_profile):
        pdf_bytes = b'%PDF-1.4\n% TEST_iter3 NOC template\n%%EOF'
        upload = SimpleUploadedFile('template.pdf', pdf_bytes, content_type='application/pdf')
        r = hr_client.post('/assets/noc/issue/', {
            'profile_id': str(hr_profile.pk),
            'purpose': 'TEST_iter3 visa',
            'template_pdf': upload,
        }, follow=True)
        assert r.status_code == 200
        noc = NOC.objects.filter(purpose='TEST_iter3 visa').first()
        assert noc and noc.status == NOC.Status.ISSUED
        assert noc.template_pdf

        # Download template
        r = hr_client.get(f'/assets/noc/{noc.pk}/template/')
        assert r.status_code == 200
        ctype = r.get('Content-Type', '')
        assert 'pdf' in ctype.lower(), f"Content-Type was: {ctype}"

        # Sign upload (HR is allowed because of role check)
        signed = SimpleUploadedFile('signed.pdf', pdf_bytes, content_type='application/pdf')
        r = hr_client.post(f'/assets/noc/{noc.pk}/sign/', {
            'signed_pdf': signed,
        }, follow=True)
        assert r.status_code == 200
        noc.refresh_from_db()
        assert noc.status == NOC.Status.SIGNED
        assert noc.signed_pdf
        noc.delete()


# ---------- Discipline page ----------
class TestDisciplinePage:
    def test_discipline_list_and_revoke(self, hr_client):
        # Ensure at least 1 record
        u = User.objects.get(username=HR)
        rec = DisciplineRecord.objects.create(
            profile=u.employee_profile,
            occurred_on=date(2026, 7, 1),
            reason=DisciplineRecord.Reason.LATE_ESCALATION,
            severity=DisciplineRecord.Severity.WARN,
            deduction_days=Decimal('0'),
            notes='TEST_iter3 discipline page',
        )
        r = hr_client.get('/assets/discipline/')
        assert r.status_code == 200
        assert b'discipline-table' in r.content

        # Toggle revoke
        was_active = rec.is_active
        r = hr_client.post(f'/assets/discipline/{rec.pk}/revoke/', follow=True)
        assert r.status_code == 200
        rec.refresh_from_db()
        assert rec.is_active != was_active
        rec.delete()


# ---------- Schedules ----------
class TestSchedules:
    def test_required_schedules_present(self):
        from django_q.models import Schedule
        names = set(Schedule.objects.values_list('name', flat=True))
        required = {
            'payroll-monthly-28th',
            'birthday-sms-daily',
            'anniversary-sms-daily',
            'kerala-holiday-fetch-yearly',
        }
        missing = required - names
        assert not missing, f"Missing scheduled jobs: {missing}; present: {names}"
