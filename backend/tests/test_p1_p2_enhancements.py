"""
P1+P2 backend integration tests for AEC HR SuperApp.

Covers:
  - Leave: list, create, decision (approve/reject), cancel
  - Document vault unlock/relock
  - Live presence JSON endpoint (HR vs Staff)
  - Malayalam i18n toggle
  - HTML email content type
  - 2FA setup/verify (full TOTP round-trip)
  - qcluster RUNNING via supervisorctl
  - 28th auto-schedule presence in django_q

NOTE: Uses public preview URL (Django session auth + CSRF).
"""
import os
import re
import subprocess
import time
import pytest
import requests

BASE_URL = "https://489d41fa-fbc6-49f2-9560-ced4ced3827a.preview.emergentagent.com"

HR = ("hr_aec", "hrpassword123")
MD = ("md_aec", "adminpassword123")


# ---------- Helpers ---------- #

def _login(session: requests.Session, username: str, password: str):
    """Django session login via /accounts/login/ with CSRF."""
    r = session.get(f"{BASE_URL}/accounts/login/", timeout=15)
    assert r.status_code == 200, f"Login GET failed {r.status_code}"
    csrf = session.cookies.get('csrftoken')
    headers = {"Referer": f"{BASE_URL}/accounts/login/"}
    r = session.post(
        f"{BASE_URL}/accounts/login/",
        data={"csrfmiddlewaretoken": csrf, "username": username, "password": password},
        headers=headers,
        allow_redirects=False,
        timeout=15,
    )
    assert r.status_code in (302, 303), f"Login POST got {r.status_code}: {r.text[:200]}"
    return r


def _csrf_post(session: requests.Session, path: str, data: dict, allow_redirects=False):
    csrf = session.cookies.get('csrftoken')
    data = {**data, "csrfmiddlewaretoken": csrf}
    headers = {"Referer": f"{BASE_URL}{path}"}
    return session.post(
        f"{BASE_URL}{path}",
        data=data,
        headers=headers,
        allow_redirects=allow_redirects,
        timeout=15,
    )


@pytest.fixture
def hr_session():
    s = requests.Session()
    _login(s, *HR)
    return s


# ---------- qcluster + scheduler ---------- #

class TestQClusterAndSchedule:
    """Verify the real qcluster worker is RUNNING under supervisor and
    the monthly 28th schedule row exists in django_q."""

    def test_qcluster_supervisor_running(self):
        out = subprocess.run(
            ["sudo", "supervisorctl", "status", "qcluster"],
            capture_output=True, text=True, timeout=10
        )
        assert "RUNNING" in out.stdout, f"qcluster not RUNNING: {out.stdout} {out.stderr}"

    def test_qcluster_log_shows_running_marker(self):
        # Combined stdout/stderr — django_q writes its banner to stderr.
        for log in ("/var/log/supervisor/qcluster.err.log",
                    "/var/log/supervisor/qcluster.out.log"):
            if os.path.exists(log):
                with open(log) as f:
                    if "Q Cluster" in f.read():
                        return
        pytest.fail("'Q Cluster ... running.' marker not found in qcluster logs")

    def test_28th_payroll_schedule_registered(self):
        script = (
            "import django, os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','aec_hr_superapp.settings'); "
            "django.setup(); "
            "from django_q.models import Schedule; "
            "s = Schedule.objects.filter(name='payroll-monthly-28th').first(); "
            "print('FOUND' if s else 'MISSING', "
            "s.func if s else '', s.schedule_type if s else '', "
            "s.next_run.day if s else '')"
        )
        r = subprocess.run(
            ["/root/.venv/bin/python", "-c", script],
            capture_output=True, text=True, cwd="/app", timeout=30,
        )
        assert "FOUND" in r.stdout, f"Schedule missing: {r.stdout} | {r.stderr}"
        assert "payroll.service.scheduled_monthly_generation" in r.stdout
        assert " M " in r.stdout  # monthly type
        assert r.stdout.strip().endswith("28")


# ---------- Leave flows ---------- #

class TestLeaveFlows:
    def test_hr_leave_list_renders(self, hr_session):
        r = hr_session.get(f"{BASE_URL}/leave/", timeout=15)
        assert r.status_code == 200
        assert b'data-testid="pending-table"' in r.content
        assert b'data-testid="leave-history-table"' in r.content

    def test_hr_leave_new_form_renders(self, hr_session):
        r = hr_session.get(f"{BASE_URL}/leave/new/", timeout=15)
        assert r.status_code == 200
        assert b'data-testid="leave-create-form"' in r.content
        assert b'data-testid="leave-submit"' in r.content

    def test_full_create_approve_flow(self, hr_session):
        unique = f"TEST_p1p2_create_{int(time.time()*1000)}"
        # Create a leave
        r = _csrf_post(hr_session, "/leave/new/", {
            "leave_type": "CL",
            "start_date": "2026-09-15",
            "end_date": "2026-09-15",
            "reason": unique,
        }, allow_redirects=False)
        assert r.status_code in (302, 303), f"Create got {r.status_code}: {r.text[:200]}"
        assert "/leave/" in r.headers.get("Location", "")

        # Find the new pending pk via shell (LeaveRequest has Meta.ordering=['-created_at'],
        # so we explicitly order_by('-pk') to grab the most-recently inserted row)
        find_pk = (
            "import django, os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','aec_hr_superapp.settings'); "
            "django.setup(); "
            "from core.models import LeaveRequest; "
            f"lr = LeaveRequest.objects.filter(reason='{unique}').order_by('-pk').first(); "
            "print(lr.pk if lr else 0, lr.status if lr else '')"
        )
        out = subprocess.run(["/root/.venv/bin/python", "-c", find_pk],
                             capture_output=True, text=True, cwd="/app", timeout=20)
        parts = out.stdout.strip().split()
        assert parts and parts[0].isdigit() and int(parts[0]) > 0, f"Leave not created: {out.stdout} {out.stderr}"
        pk = int(parts[0])
        assert parts[1] == "PENDING"

        # Approve
        r = _csrf_post(hr_session, f"/leave/{pk}/decision/", {"action": "approve"})
        assert r.status_code in (302, 303), f"Decision got {r.status_code}"

        # Verify status APPROVED + AuditLog created
        verify = (
            "import django, os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','aec_hr_superapp.settings'); "
            "django.setup(); "
            "from core.models import LeaveRequest, AuditLog; "
            f"lr = LeaveRequest.objects.get(pk={pk}); "
            "al = AuditLog.objects.filter(action='LEAVE_APPROVED', "
            f"details__pk={pk}).exists(); "
            "print(lr.status, al)"
        )
        out = subprocess.run(["/root/.venv/bin/python", "-c", verify],
                             capture_output=True, text=True, cwd="/app", timeout=20)
        assert "APPROVED True" in out.stdout, f"Approve not persisted: {out.stdout}"

    def test_create_and_cancel_own_leave(self, hr_session):
        unique = f"TEST_p1p2_cancel_{int(time.time()*1000)}"
        r = _csrf_post(hr_session, "/leave/new/", {
            "leave_type": "CL", "start_date": "2026-09-20", "end_date": "2026-09-20",
            "reason": unique,
        })
        assert r.status_code in (302, 303)
        find_pk = (
            "import django, os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','aec_hr_superapp.settings'); "
            "django.setup(); from core.models import LeaveRequest; "
            f"lr = LeaveRequest.objects.filter(reason='{unique}').order_by('-pk').first(); "
            "print(lr.pk)"
        )
        out = subprocess.run(["/root/.venv/bin/python", "-c", find_pk],
                             capture_output=True, text=True, cwd="/app", timeout=20)
        pk = int(out.stdout.strip())

        r = _csrf_post(hr_session, f"/leave/{pk}/cancel/", {})
        assert r.status_code in (302, 303)
        verify = (
            "import django, os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','aec_hr_superapp.settings'); "
            "django.setup(); from core.models import LeaveRequest; "
            f"print(LeaveRequest.objects.get(pk={pk}).status)"
        )
        out = subprocess.run(["/root/.venv/bin/python", "-c", verify],
                             capture_output=True, text=True, cwd="/app", timeout=20)
        assert "CANCELLED" in out.stdout


# ---------- Live presence ---------- #

class TestLivePresence:
    def test_hr_live_presence_returns_json(self, hr_session):
        r = hr_session.get(f"{BASE_URL}/attendance/api/live/", timeout=15)
        assert r.status_code == 200
        data = r.json()
        for key in ("as_of", "labels", "present", "total", "markers"):
            assert key in data, f"missing key {key}"
        assert isinstance(data["labels"], list)
        assert isinstance(data["markers"], list)

    def test_attendance_dashboard_has_live_stamp(self, hr_session):
        r = hr_session.get(f"{BASE_URL}/attendance/dashboard/", timeout=15)
        assert r.status_code == 200
        assert b'id="live-stamp"' in r.content
        assert b'data-testid="live-stamp"' in r.content


# ---------- Document vault unlock/relock ---------- #

class TestDocumentVault:
    def test_hr_verify_lists_locked_profiles(self, hr_session):
        pytest.skip("Locked profiles section removed from HR verification page per user request")

    def test_unlock_then_relock_persists(self, hr_session):
        # Find any non-MD/HR locked profile (pk)
        find = (
            "import django, os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','aec_hr_superapp.settings'); "
            "django.setup(); from core.models import EmployeeProfile; "
            "p = EmployeeProfile.objects.exclude(user__username__in=['md_aec','hr_aec']).filter(user__is_active=True).first(); "
            "print(p.pk if p else 0, p.is_locked if p else '')"
        )
        out = subprocess.run(["/root/.venv/bin/python", "-c", find],
                             capture_output=True, text=True, cwd="/app", timeout=20)
        parts = out.stdout.strip().split()
        if not parts or parts[0] == "0":
            pytest.skip("No non-MD/HR profile to test unlock/relock")
        pk = int(parts[0])

        r = _csrf_post(hr_session, f"/onboarding/unlock/{pk}/", {"action": "unlock"})
        assert r.status_code in (302, 303)
        v = subprocess.run(["/root/.venv/bin/python", "-c",
                            f"import django,os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','aec_hr_superapp.settings'); django.setup(); from core.models import EmployeeProfile; print(EmployeeProfile.objects.get(pk={pk}).is_locked)"],
                           capture_output=True, text=True, cwd="/app", timeout=20)
        assert "False" in v.stdout, f"unlock not persisted: {v.stdout}"

        r = _csrf_post(hr_session, f"/onboarding/unlock/{pk}/", {"action": "relock"})
        assert r.status_code in (302, 303)
        v = subprocess.run(["/root/.venv/bin/python", "-c",
                            f"import django,os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','aec_hr_superapp.settings'); django.setup(); from core.models import EmployeeProfile; print(EmployeeProfile.objects.get(pk={pk}).is_locked)"],
                           capture_output=True, text=True, cwd="/app", timeout=20)
        assert "True" in v.stdout


# ---------- i18n Malayalam ---------- #

class TestMalayalamI18n:
    def test_switch_to_ml_renders_malayalam_dashboard(self, hr_session):
        # Switch to Malayalam via Django's built-in set_language
        csrf = hr_session.cookies.get('csrftoken')
        r = hr_session.post(
            f"{BASE_URL}/i18n/setlang/",
            data={"csrfmiddlewaretoken": csrf, "language": "ml", "next": "/dashboard/"},
            headers={"Referer": f"{BASE_URL}/dashboard/"},
            allow_redirects=False, timeout=15,
        )
        assert r.status_code in (302, 303)

        r = hr_session.get(f"{BASE_URL}/dashboard/", timeout=15)
        assert r.status_code == 200
        body = r.content.decode("utf-8", errors="ignore")
        # At least one Malayalam glyph translation should appear
        assert ("അവധി" in body) or ("ലോഗൗട്ട്" in body) or ("ഹാജർ" in body), \
            "Malayalam translations not rendered"

        # Switch back to en
        csrf = hr_session.cookies.get('csrftoken')
        hr_session.post(
            f"{BASE_URL}/i18n/setlang/",
            data={"csrfmiddlewaretoken": csrf, "language": "en", "next": "/dashboard/"},
            headers={"Referer": f"{BASE_URL}/dashboard/"},
            allow_redirects=False, timeout=15,
        )
        r = hr_session.get(f"{BASE_URL}/dashboard/", timeout=15)
        body = r.content.decode("utf-8", errors="ignore")
        assert "Logout" in body, "English not restored"


# ---------- HTML email ---------- #

class TestHtmlEmail:
    """After triggering a leave create, the Django console email backend
    prints a multipart message that includes 'Content-Type: text/html'.
    We check the supervisor backend log."""

    def test_html_email_content_type_in_backend_log(self, hr_session):
        # Trigger a leave creation
        r = _csrf_post(hr_session, "/leave/new/", {
            "leave_type": "CL", "start_date": "2026-09-25", "end_date": "2026-09-25",
            "reason": "TEST_html_email_check",
        })
        assert r.status_code in (302, 303)
        time.sleep(2)

        # Console email backend writes to whichever process served the request
        # (uvicorn on :8001 OR Django runserver shim on :3000 → frontend supervisor).
        log_paths = [
            "/var/log/supervisor/backend.out.log",
            "/var/log/supervisor/backend.err.log",
            "/var/log/supervisor/frontend.out.log",
            "/var/log/supervisor/frontend.err.log",
        ]
        haystack = ""
        for p in log_paths:
            if os.path.exists(p):
                with open(p, errors="ignore") as f:
                    haystack += f.read()
        assert "text/html" in haystack, "HTML alternative not present in console email output"


# ---------- 2FA full round-trip ---------- #

class TestMd2FA:
    def test_full_md_2fa_round_trip(self):
        """
        1) MD logs in
        2) Any non-exempt path redirects to /2fa/setup/
        3) GET /2fa/setup/ -> QR + secret rendered
        4) POST valid TOTP token -> session.md_2fa_verified=True; redirect to /dashboard/
        5) /dashboard/ now reachable (200)

        Cleanup: delete confirmed devices to leave the system in a clean state.
        """
        # Always reset: delete any confirmed devices first
        reset_script = (
            "import django,os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','aec_hr_superapp.settings'); django.setup(); "
            "from django_otp.plugins.otp_totp.models import TOTPDevice; "
            "from core.models import User; "
            "u = User.objects.get(username='md_aec'); "
            "TOTPDevice.objects.filter(user=u).delete(); "
            "print('reset')"
        )
        subprocess.run(["/root/.venv/bin/python", "-c", reset_script],
                       capture_output=True, text=True, cwd="/app", timeout=20)

        s = requests.Session()
        _login(s, *MD)

        # /dashboard/ should redirect to /2fa/setup/
        r = s.get(f"{BASE_URL}/dashboard/", allow_redirects=False, timeout=15)
        assert r.status_code in (302, 303)
        assert "/2fa/setup/" in r.headers.get("Location", "")

        # GET setup
        r = s.get(f"{BASE_URL}/2fa/setup/", timeout=15)
        assert r.status_code == 200
        assert b'data-testid="totp-qr"' in r.content
        assert b'data-testid="totp-secret"' in r.content
        assert b'data:image/png;base64,' in r.content

        # Generate a valid TOTP token via shell using the unconfirmed device
        token_script = (
            "import django,os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','aec_hr_superapp.settings'); django.setup(); "
            "from django_otp.plugins.otp_totp.models import TOTPDevice; "
            "from django_otp.oath import totp as _totp; "
            "from core.models import User; "
            "u = User.objects.get(username='md_aec'); "
            "d = TOTPDevice.objects.filter(user=u, confirmed=False).first(); "
            "tok = _totp(d.bin_key, step=d.step, t0=d.t0, digits=d.digits); "
            "print(f'{tok:0{d.digits}d}')"
        )
        out = subprocess.run(["/root/.venv/bin/python", "-c", token_script],
                             capture_output=True, text=True, cwd="/app", timeout=20)
        token = out.stdout.strip().splitlines()[-1]
        assert re.fullmatch(r"\d{6}", token), f"Bad token: {out.stdout} | {out.stderr}"

        r = _csrf_post(s, "/2fa/setup/", {"token": token})
        assert r.status_code in (302, 303), f"setup POST got {r.status_code}"
        assert "/dashboard/" in r.headers.get("Location", "")

        # Confirm /dashboard/ now reachable
        r = s.get(f"{BASE_URL}/dashboard/", timeout=15)
        assert r.status_code == 200
        assert b"Dashboard" in r.content or b"AEC" in r.content

        # Verify a confirmed device exists
        check = subprocess.run(["/root/.venv/bin/python", "-c",
                                "import django,os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','aec_hr_superapp.settings'); django.setup(); "
                                "from django_otp.plugins.otp_totp.models import TOTPDevice; "
                                "from core.models import User; "
                                "print(TOTPDevice.objects.filter(user__username='md_aec', confirmed=True).count())"],
                               capture_output=True, text=True, cwd="/app", timeout=20)
        assert "1" in check.stdout

    def test_md_2fa_verify_after_session_clear(self):
        """After session.md_2fa_verified is cleared, MD should be redirected
        to /2fa/verify/ (since a confirmed device now exists from the prior test).
        Posting a valid TOTP unlocks the session."""
        s = requests.Session()
        _login(s, *MD)

        # Hit dashboard -> should redirect to /2fa/verify/ now (confirmed device exists)
        r = s.get(f"{BASE_URL}/dashboard/", allow_redirects=False, timeout=15)
        assert r.status_code in (302, 303)
        assert "/2fa/verify/" in r.headers.get("Location", "")

        r = s.get(f"{BASE_URL}/2fa/verify/", timeout=15)
        assert r.status_code == 200
        assert b'data-testid="totp-verify-input"' in r.content

        # Invalid token first
        r = _csrf_post(s, "/2fa/verify/", {"token": "000000"})
        assert r.status_code in (302, 303)
        # Should redirect back to verify (not dashboard)
        assert "/2fa/verify/" in r.headers.get("Location", "")

        # Reset device last_t so we can reuse the current TOTP step (TOTPDevice
        # records last_t to prevent token replay; an integration test needs to
        # bypass this safely without waiting for the next 30s window).
        reset_lastt = (
            "import django,os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','aec_hr_superapp.settings'); django.setup(); "
            "from django_otp.plugins.otp_totp.models import TOTPDevice; "
            "TOTPDevice.objects.filter(user__username='md_aec', confirmed=True).update(last_t=-1, throttling_failure_count=0); "
            "print('reset')"
        )
        subprocess.run(["/root/.venv/bin/python", "-c", reset_lastt],
                       capture_output=True, text=True, cwd="/app", timeout=20)

        # Valid token
        token_script = (
            "import django,os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','aec_hr_superapp.settings'); django.setup(); "
            "from django_otp.plugins.otp_totp.models import TOTPDevice; "
            "from django_otp.oath import totp as _totp; "
            "from core.models import User; "
            "d = TOTPDevice.objects.filter(user__username='md_aec', confirmed=True).first(); "
            "tok = _totp(d.bin_key, step=d.step, t0=d.t0, digits=d.digits); "
            "print(f'{tok:0{d.digits}d}')"
        )
        out = subprocess.run(["/root/.venv/bin/python", "-c", token_script],
                             capture_output=True, text=True, cwd="/app", timeout=20)
        token = out.stdout.strip().splitlines()[-1]

        r = _csrf_post(s, "/2fa/verify/", {"token": token})
        assert r.status_code in (302, 303)
        assert "/dashboard/" in r.headers.get("Location", "/dashboard/")

        # Cleanup: delete TOTP devices so other test runs / MD login flow stays clean
        reset = (
            "import django,os; os.environ.setdefault('DJANGO_SETTINGS_MODULE','aec_hr_superapp.settings'); django.setup(); "
            "from django_otp.plugins.otp_totp.models import TOTPDevice; "
            "from core.models import User; "
            "TOTPDevice.objects.filter(user__username='md_aec').delete(); print('cleaned')"
        )
        subprocess.run(["/root/.venv/bin/python", "-c", reset],
                       capture_output=True, text=True, cwd="/app", timeout=20)
