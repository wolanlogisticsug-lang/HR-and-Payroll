"""
URL configuration for aec_hr_superapp project.
"""
from django.contrib import admin
from django.contrib.auth.decorators import login_required
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from django.shortcuts import redirect, render
from django.contrib.auth import views as auth_views
from core.views import setup_owner, signup, reimbursements_view, tasks_view

@login_required
def dashboard(request):
    ctx = {}
    u = request.user
    from core.models import EmployeeProfile, Department, Attendance, LeaveRequest
    from django.utils import timezone
    from django.db.models import F

    today = timezone.now().date()

    # --- Fetch current user profile ---
    my_profile = EmployeeProfile.objects.filter(
        user__email=u.email
    ).select_related('reporting_manager__user').order_by(
        F('date_of_joining').desc(nulls_last=True),
        F('designation').desc(nulls_last=True),
        '-id'
    ).first()

    if not my_profile and not u.is_superuser:
        from decimal import Decimal
        dept, _ = Department.objects.get_or_create(name="HR & Administration" if u.role == 'HR' else "General")
        my_profile = EmployeeProfile.objects.create(
            user=u,
            department=dept,
            designation="HR Administrator" if u.role == 'HR' else "Staff",
            basic_salary=Decimal('40000'),
            is_active=True,
            is_locked=True,
            probation_status='PERMANENT',
        )

    if my_profile:
        ctx['my_profile'] = my_profile
        ctx['my_manager'] = my_profile.reporting_manager
    else:
        ctx['my_profile'] = None
        ctx['my_manager'] = None

    if u.role == 'MD':
        ctx['md_stats'] = {
            'total_employees':    EmployeeProfile.objects.filter(is_active=True, probation_status__in=['PROBATION', 'PERMANENT']).count(),
            'on_probation':       EmployeeProfile.objects.filter(is_active=True, probation_status='PROBATION').count(),
            'permanent_employees':EmployeeProfile.objects.filter(is_active=True, probation_status='PERMANENT').count(),
            'present_today':      Attendance.objects.filter(date=today, is_valid=True).count(),
            'on_leave_today':     LeaveRequest.objects.filter(
                                      status='APPROVED',
                                      start_date__lte=today,
                                      end_date__gte=today
                                  ).count(),
        }

    departments = Department.objects.filter(is_active=True)
    staff_by_department = []
    for dept in departments:
        profiles = EmployeeProfile.objects.filter(department=dept).select_related('user')
        probation = profiles.filter(probation_status='PROBATION', is_active=True)
        permanent = profiles.filter(probation_status='PERMANENT', is_active=True)
        terminated = profiles.filter(is_active=False).exclude(onboarding_status='VERIFIED')
        staff_by_department.append({
            'department': dept,
            'probation': probation,
            'permanent': permanent,
            'terminated': terminated,
            'total': probation.count() + permanent.count() + terminated.count()
        })
    ctx['staff_by_department'] = staff_by_department

    # --- Team View: employees who report to the logged-in user ---
    try:
        mgr_profile = u.employee_profile
        team = mgr_profile.team_members.filter(is_active=True, probation_status__in=['PROBATION', 'PERMANENT']).select_related('user', 'department')
        ctx['team_members'] = team
    except Exception:
        ctx['team_members'] = []

    return render(request, 'dashboard.html', ctx)


@login_required
def work_logs_view(request):
    ctx = {}
    u = request.user
    from django.utils import timezone
    from django.contrib import messages
    from core.models import DailyWorkLog, EmployeeProfile
    from django.db.models import F

    today = timezone.now().date()

    # --- Fetch current user profile ---
    my_profile = EmployeeProfile.objects.filter(
        user__email=u.email
    ).select_related('reporting_manager__user').order_by(
        F('date_of_joining').desc(nulls_last=True),
        F('designation').desc(nulls_last=True),
        '-id'
    ).first()

    if request.method == 'POST' and request.POST.get('action') == 'save_work_log':
        status_text = request.POST.get('status_text', '').strip()
        hours_logged = request.POST.get('hours_logged', '8.0')
        if my_profile and status_text:
            log, created = DailyWorkLog.objects.update_or_create(
                profile=my_profile,
                date=today,
                defaults={'status_text': status_text, 'hours_logged': hours_logged}
            )
            messages.success(request, "Daily work status successfully logged.")
            return redirect('work_logs')

    if my_profile:
        ctx['my_profile'] = my_profile
        ctx['my_work_log'] = DailyWorkLog.objects.filter(profile=my_profile, date=today).first()
    else:
        ctx['my_profile'] = None
        ctx['my_work_log'] = None

    # --- Department-wise daily log report for MD, HR, and DEPT_HEAD ---
    if u.role in ['MD', 'HR', 'DEPT_HEAD']:
        logs_query = DailyWorkLog.objects.filter(date=today).select_related('profile__user', 'profile__department')
        if u.role == 'DEPT_HEAD' and my_profile:
            logs_query = logs_query.filter(profile__department=my_profile.department)
        
        dept_logs = {}
        for log in logs_query:
            dept_name = log.profile.department.name if log.profile.department else "General"
            dept_logs.setdefault(dept_name, []).append(log)
        ctx['department_work_logs'] = dept_logs

    return render(request, 'work_logs.html', ctx)


urlpatterns = [
    # Redirect base URL to dashboard, login, or setup
    path('', lambda r: redirect('dashboard') if r.user.is_authenticated else (redirect('setup') if not __import__('core').models.User.objects.exists() else redirect('login'))),
    path('setup/', setup_owner, name='setup'),
    
    path('admin/', admin.site.urls),
    path('accounts/login/', auth_views.LoginView.as_view(), name='login'),
    path('accounts/signup/', signup, name='signup'),
    path('accounts/', include('django.contrib.auth.urls')),
    path('i18n/', include('django.conf.urls.i18n')),
    path('dashboard/', dashboard, name='dashboard'),
    path('work-logs/', work_logs_view, name='work_logs'),
    path('reimbursements/', reimbursements_view, name='reimbursements'),
    path('tasks/', tasks_view, name='tasks'),
    
    # AEC Super App Modules
    path('onboarding/', include('onboarding.urls')),
    path('attendance/', include('attendance.urls')),
    path('payroll/', include('payroll.urls')),
    path('leave/', include('leave.urls')),
    path('assets/', include('assets.urls')),
    path('communications/', include('communications.urls')),
    path('notifications/', include('notifications.urls')),
]

# Serve media files in all environments (including production when DEBUG=False)
from django.views.static import serve
from django.urls import re_path
urlpatterns += [
    re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
]

if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)