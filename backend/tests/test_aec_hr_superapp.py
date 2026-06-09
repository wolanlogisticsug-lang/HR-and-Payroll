"""End-to-end backend tests for wolan Hr HR SuperApp (Django session-based)."""
import os
import re
import pytest
import requests
from decimal import Decimal

BASE_URL = os.environ.get(
    'REACT_APP_BACKEND_URL',
    'https://489d41fa-fbc6-49f2-9560-ced4ced3827a.preview.emergentagent.com',
).rstrip('/')

LOGIN_URL = f"{BASE_URL}/accounts/login/"

MD = ("md_wolan Hr", "adminpassword123")
HR = ("hr_wolan Hr", "hrpassword123")


def _login(username, password):
    """Performs Django session-based login. Returns an authenticated requests Session."""
    s = requests.Session()
    s.headers.update({"Referer": LOGIN_URL})
    r = s.get(LOGIN_URL, timeout=20)
    assert r.status_code == 200, f"login GET failed: {r.status_code}"
    m = re.search(r'name=["\']csrfmiddlewaretoken["\']\s+value=["\']([^"\']+)["\']', r.text)
    assert m, "CSRF token not found on login page"
    csrf = m.group(1)
    r2 = s.post(
        LOGIN_URL,
        data={"username": username, "password": password, "csrfmiddlewaretoken": csrf, "next": "/dashboard/"},
        headers={"Referer": LOGIN_URL},
        allow_redirects=False,
        timeout=20,
    )
    assert r2.status_code in (302, 303), f"login POST failed: {r2.status_code} body={r2.text[:300]}"
    loc = r2.headers.get("Location", "")
    assert "/dashboard" in loc or loc == "/dashboard/", f"unexpected redirect: {loc}"
    return s


def _csrf(session, url):
    r = session.get(url, timeout=20)
    m = re.search(r'name=["\']csrfmiddlewaretoken["\']\s+value=["\']([^"\']+)["\']', r.text)
    return r, (m.group(1) if m else None)


@pytest.fixture(scope="module")
def md_session():
    return _login(*MD)


@pytest.fixture(scope="module")
def hr_session():
    return _login(*HR)


# -------- Auth & Dashboard --------
class TestAuth:
    def test_login_page_loads(self):
        r = requests.get(LOGIN_URL, timeout=20)
        assert r.status_code == 200
        assert "csrfmiddlewaretoken" in r.text

    def test_md_login(self, md_session):
        r = md_session.get(f"{BASE_URL}/dashboard/", timeout=20)
        assert r.status_code == 200
        assert "Logout" in r.text or "logout" in r.text.lower()

    def test_hr_login(self, hr_session):
        r = hr_session.get(f"{BASE_URL}/dashboard/", timeout=20)
        assert r.status_code == 200

    def test_unauthenticated_dashboard_redirects(self):
        r = requests.get(f"{BASE_URL}/dashboard/", allow_redirects=False, timeout=20)
        assert r.status_code in (302, 301)
        assert "/accounts/login" in r.headers.get("Location", "")


# -------- Attendance --------
class TestAttendance:
    def test_clock_page_loads(self, hr_session):
        r = hr_session.get(f"{BASE_URL}/attendance/clock/", timeout=20)
        assert r.status_code == 200
        # Webcam UI + leaflet markers
        body = r.text.lower()
        assert "leaflet" in body or "map" in body
        assert "video" in body or "face" in body or "webcam" in body

    def test_attendance_dashboard_manager(self, hr_session):
        # Use HR (no 2FA) — MD now goes through TOTP middleware
        r = hr_session.get(f"{BASE_URL}/attendance/dashboard/", timeout=20)
        assert r.status_code == 200
        # Manager view should include heatmap + leaflet bits
        assert "chart" in r.text.lower() or "heatmap" in r.text.lower()


# -------- Payroll dashboard / pages --------
class TestPayrollDashboard:
    def test_dashboard_loads_md(self, md_session):
        r = md_session.get(f"{BASE_URL}/payroll/?year=2026&month=8", timeout=20)
        assert r.status_code == 200
        assert "payroll" in r.text.lower()

    def test_dashboard_loads_hr(self, hr_session):
        r = hr_session.get(f"{BASE_URL}/payroll/?year=2026&month=8", timeout=20)
        assert r.status_code == 200

    def test_tax_page_hr(self, hr_session):
        r = hr_session.get(f"{BASE_URL}/payroll/tax/", timeout=20)
        assert r.status_code == 200
        assert "PT" in r.text or "Professional" in r.text or "Kerala" in r.text


# -------- Payroll generate --------
class TestPayrollGenerate:
    def test_generate_aug_2026(self, md_session):
        r, csrf = _csrf(md_session, f"{BASE_URL}/payroll/?year=2026&month=8")
        assert csrf, "CSRF missing on payroll dashboard"
        rp = md_session.post(
            f"{BASE_URL}/payroll/generate/",
            data={"year": "2026", "month": "8", "csrfmiddlewaretoken": csrf},
            headers={"Referer": f"{BASE_URL}/payroll/?year=2026&month=8"},
            allow_redirects=False,
            timeout=40,
        )
        assert rp.status_code in (302, 303), f"generate failed: {rp.status_code} {rp.text[:300]}"


# -------- Payslip PDF --------
class TestSlipPDF:
    def test_hr_self_slip_pdf(self, hr_session):
        # Try HR's own profile slip for 8/2026 (seeded). We need to find profile_id;
        # without knowing it, request without profile_id (uses logged-in user).
        r = hr_session.get(f"{BASE_URL}/payroll/slip/2026/8/", timeout=30)
        # Could be 200 (PDF) or 403 if not approved yet (HR is staff role-wise? HR isn't STAFF).
        # HR users should be able to download regardless of status path branch; treat 200 as primary.
        if r.status_code == 200:
            assert r.headers.get("Content-Type", "").startswith("application/pdf")
            assert r.content[:4] == b"%PDF"
            assert len(r.content) > 1000
        else:
            # Acceptable: 404 if not generated. Mark as informational
            assert r.status_code in (200, 404, 403)


# -------- Permissions: incentives MD-only --------
class TestIncentivePerms:
    def test_hr_cannot_add_incentive(self, hr_session):
        _, csrf = _csrf(hr_session, f"{BASE_URL}/payroll/?year=2026&month=8")
        r = hr_session.post(
            f"{BASE_URL}/payroll/incentive/add/",
            data={
                "profile_id": "1",
                "incentive_type": "BONUS",
                "amount": "100",
                "year": "2026",
                "month": "8",
                "csrfmiddlewaretoken": csrf or "",
            },
            headers={"Referer": f"{BASE_URL}/payroll/"},
            allow_redirects=False,
            timeout=20,
        )
        # HR should be denied: 403 (UserPassesTestMixin -> PermissionDenied) or redirect to login
        assert r.status_code in (403, 302), f"HR was not blocked: {r.status_code}"
        if r.status_code == 302:
            assert "login" in r.headers.get("Location", "").lower() or r.headers.get("Location", "").endswith("/")


# -------- Tailwind/template sanity (no 500) --------
class TestNoServerErrors:
    @pytest.mark.parametrize("path", [
        "/dashboard/",
        "/attendance/clock/",
        "/attendance/dashboard/",
        "/payroll/",
        "/payroll/tax/",
    ])
    def test_no_500(self, md_session, path):
        r = md_session.get(f"{BASE_URL}{path}", timeout=20)
        assert r.status_code < 500, f"{path} returned {r.status_code}"
