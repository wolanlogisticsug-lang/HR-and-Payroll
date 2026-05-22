"""
Lightweight JSON APIs used by the Zoho-style shell:
  - /api/search/         → global Cmd/Ctrl+K command palette
  - /api/notifications/  → topbar bell dropdown
Both are session-authenticated (already-loggedin user only).
"""
from datetime import timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone


def _is_manager(user):
    return getattr(user, 'role', None) in ('HR', 'DEPT_HEAD', 'MD')


@login_required
def search(request):
    """Global search across employees, leave requests, payroll months, modules."""
    from core.models import EmployeeProfile, LeaveRequest, Payroll

    q = (request.GET.get('q') or '').strip()
    user = request.user
    results = {'employees': [], 'leaves': [], 'payroll': [], 'pages': []}

    # ── Static pages (always visible, filter client-side or here) ──
    pages = [
        ('Dashboard', reverse('dashboard'),
         'M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3'),
        ('Attendance Dashboard', reverse('attendance:dashboard'),
         'M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6'),
        ('Clock In / Out', reverse('attendance:clock'),
         'M12 8v4l3 3'),
        ('Leave Requests', reverse('leave:list'),
         'M8 7V3m8 4V3m-9 8h10'),
        ('Leave Calendar', reverse('leave:calendar'),
         'M8 7V3m8 4V3m-9 8h10'),
        ('Payroll', reverse('payroll:dashboard'),
         'M12 8c-1.657 0-3 .895-3 2'),
        ('Tax & Statutory', reverse('payroll:tax'),
         'M9 12h6'),
        ('Assets & NOC', reverse('assets:dashboard'),
         'M20 7l-8-4-8 4'),
    ]
    if user.role == 'HR':
        pages.append(('Onboarding Dashboard', reverse('onboarding:onboarding_dashboard'), ''))
        pages.append(('Send Promotion Letter', reverse('communications:send_promotion'), ''))
        pages.append(('Verify Candidates', reverse('onboarding:hr_verify_list'), ''))

    ql = q.lower()
    if q:
        results['pages'] = [
            {'label': name, 'url': url}
            for name, url, _ in pages if ql in name.lower()
        ][:6]
    else:
        results['pages'] = [{'label': name, 'url': url} for name, url, _ in pages[:6]]

    # ── Employees ──
    # Managers (HR/MD/DEPT_HEAD) see all; staff only sees themselves.
    if _is_manager(user):
        emp_qs = EmployeeProfile.objects.select_related('user', 'department').filter(is_active=True, probation_status__in=[EmployeeProfile.ProbationStatus.PROBATION, EmployeeProfile.ProbationStatus.PERMANENT])
    else:
        emp_qs = EmployeeProfile.objects.select_related('user', 'department').filter(user=user)

    if q:
        emp_qs = emp_qs.filter(
            Q(employee_id__icontains=q)
            | Q(user__first_name__icontains=q)
            | Q(user__last_name__icontains=q)
            | Q(user__username__icontains=q)
            | Q(user__email__icontains=q)
            | Q(designation__icontains=q)
            | Q(department__name__icontains=q)
        )
    results['employees'] = [
        {
            'id': p.id,
            'name': p.user.get_full_name() or p.user.username,
            'meta': f"{p.employee_id} · {p.department.name}"
                    + (f" · {p.designation}" if p.designation else ''),
            'url': reverse('onboarding:staff_detail', kwargs={'profile_id': p.id}),
        }
        for p in emp_qs[:8]
    ]

    # ── Leave requests ──
    if _is_manager(user):
        lv_qs = LeaveRequest.objects.select_related('profile__user').all()
    else:
        lv_qs = LeaveRequest.objects.select_related('profile__user').filter(profile__user=user)
    if q:
        lv_qs = lv_qs.filter(
            Q(profile__employee_id__icontains=q)
            | Q(profile__user__first_name__icontains=q)
            | Q(profile__user__username__icontains=q)
            | Q(reason__icontains=q)
            | Q(leave_type__icontains=q)
            | Q(status__icontains=q)
        )
    lv_qs = lv_qs.order_by('-created_at')[:6]
    results['leaves'] = [
        {
            'id': l.id,
            'name': f"{l.profile.user.get_full_name() or l.profile.user.username} · {l.get_leave_type_display()}",
            'meta': f"{l.start_date} → {l.end_date} · {l.get_status_display()}",
            'url': reverse('leave:list'),
            'status': l.status,
        }
        for l in lv_qs
    ]

    # ── Payroll ──
    if _is_manager(user):
        pr_qs = Payroll.objects.select_related('profile__user').all()
    else:
        pr_qs = Payroll.objects.select_related('profile__user').filter(profile__user=user)
    if q:
        pr_qs = pr_qs.filter(
            Q(profile__employee_id__icontains=q)
            | Q(profile__user__first_name__icontains=q)
            | Q(profile__user__username__icontains=q)
            | Q(status__icontains=q)
        )
    pr_qs = pr_qs.order_by('-month')[:6]
    results['payroll'] = [
        {
            'id': p.id,
            'name': f"{p.profile.user.get_full_name() or p.profile.user.username} · {p.month.strftime('%b %Y')}",
            'meta': f"Net ₹{p.net_salary} · {p.get_status_display()}",
            'url': reverse('payroll:dashboard') + f"?month={p.month.month}&year={p.month.year}",
        }
        for p in pr_qs
    ]

    return JsonResponse(results)


@login_required
def notifications(request):
    """Notifications dropdown payload."""
    from core.models import EmployeeProfile, LeaveRequest

    user = request.user
    today = timezone.now().date()
    items = []

    # HR / managers: pending leave requests
    if user.role in ('HR', 'DEPT_HEAD', 'MD'):
        pending = LeaveRequest.objects.select_related('profile__user').filter(
            status='PENDING'
        ).order_by('-created_at')[:5]
        for l in pending:
            items.append({
                'icon': 'leave',
                'tone': 'amber',
                'title': f"Leave request · {l.profile.user.get_full_name() or l.profile.user.username}",
                'body': f"{l.get_leave_type_display()} · {l.start_date} → {l.end_date}",
                'url': reverse('leave:list'),
                'time': l.created_at.strftime('%b %d'),
            })

    # HR: pending verifications
    if user.role == 'HR':
        pending_verif = EmployeeProfile.objects.select_related('user', 'department').filter(
            onboarding_status='PENDING'
        )[:5]
        for p in pending_verif:
            items.append({
                'icon': 'verify',
                'tone': 'orange',
                'title': f"Verify · {p.user.get_full_name() or p.user.username}",
                'body': f"{p.department.name}{(' · ' + p.designation) if p.designation else ''}",
                'url': reverse('onboarding:hr_verify_list'),
                'time': p.created_at.strftime('%b %d') if p.created_at else '',
            })

        # Probation ending within 14 days
        soon = EmployeeProfile.objects.select_related('user').filter(
            is_active=True,
            probation_status='PROBATION',
            probation_end_date__lte=today + timedelta(days=14),
            probation_end_date__gte=today,
        )[:5]
        for p in soon:
            items.append({
                'icon': 'clock',
                'tone': 'amber',
                'title': f"Probation ending · {p.user.get_full_name() or p.user.username}",
                'body': f"Ends {p.probation_end_date.strftime('%b %d, %Y')}",
                'url': reverse('onboarding:onboarding_dashboard'),
                'time': p.probation_end_date.strftime('%b %d'),
            })

    # Self: own pending leaves
    if user.role == 'STAFF':
        own_pending = LeaveRequest.objects.filter(
            profile__user=user, status='PENDING'
        ).order_by('-created_at')[:3]
        for l in own_pending:
            items.append({
                'icon': 'leave',
                'tone': 'blue',
                'title': "Your leave is awaiting approval",
                'body': f"{l.get_leave_type_display()} · {l.start_date} → {l.end_date}",
                'url': reverse('leave:list'),
                'time': l.created_at.strftime('%b %d'),
            })

    return JsonResponse({'count': len(items), 'items': items})
