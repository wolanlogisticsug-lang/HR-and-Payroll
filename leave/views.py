"""
Leave Request views.

- Staff: create / cancel own pending requests, view own history.
- HR / MD / Department Head: review pending requests, approve / reject /
  redirect to another approver (chain: req -> mgr -> higher -> MD/HR).
- Probation: 1 leave/month (2 half-days). Permanent: 2 leaves/month
  (4 half-days). Enforced server-side on create.
"""
from datetime import date, datetime
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.views import View

from core.models import AuditLog, EmployeeProfile, Holiday, LeaveRequest, User
from twofa.emails import send_html_mail


def _half_day_count(leave: LeaveRequest) -> Decimal:
    """Half-day units consumed by a leave request.
    HALF=1, FULL/CASUAL/EMERGENCY = 2 * duration_days."""
    days = Decimal(leave.duration_days)
    if leave.leave_type == LeaveRequest.LeaveType.HALF_DAY:
        return Decimal('1')
    return days * Decimal('2')


def _quota_for(profile: EmployeeProfile) -> Decimal:
    """Allowed half-days per month by probation status."""
    from core.models import EmployeeProfile as EP
    if profile.probation_status == EP.ProbationStatus.PROBATION:
        return Decimal('2')   # 1 leave = 2 half-days
    return Decimal('4')       # 2 leaves = 4 half-days


class HROrMDMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        u = self.request.user
        return u.is_authenticated and u.role in [User.Role.HR, User.Role.MD, User.Role.DEPT_HEAD]


class LeaveListView(LoginRequiredMixin, View):
    def get(self, request):
        u = request.user
        is_manager = u.role in [User.Role.HR, User.Role.MD, User.Role.DEPT_HEAD]
        today = date.today()

        on_leave_today = LeaveRequest.objects.none()
        if is_manager:
            on_leave_today = LeaveRequest.objects.filter(
                status=LeaveRequest.Status.APPROVED,
                start_date__lte=today,
                end_date__gte=today,
            ).select_related(
                'profile__user', 'profile__department'
            ).order_by('profile__department__name', 'start_date')
            
            if u.role == User.Role.DEPT_HEAD:
                on_leave_today = on_leave_today.filter(profile__department__head=u)

        # ── MD gets full Leave Report along with pending & history ──────────
        if is_manager:
            qs = LeaveRequest.objects.select_related(
                'profile__user', 'profile__department', 'approved_by'
            ).order_by('profile__department__name', 'start_date')
            if u.role == User.Role.DEPT_HEAD:
                qs = qs.filter(profile__department__head=u)
        else:
            try:
                profile = u.employee_profile
                qs = LeaveRequest.objects.filter(profile=profile).order_by('-created_at')
            except EmployeeProfile.DoesNotExist:
                qs = LeaveRequest.objects.none()

        pending = qs.filter(status=LeaveRequest.Status.PENDING)
        history = qs.exclude(status=LeaveRequest.Status.PENDING).order_by('-created_at')[:50]

        # Approvers for redirect dropdown (managers only)
        approvers = []
        if is_manager:
            approvers = list(User.objects.filter(
                role__in=[User.Role.HR, User.Role.MD, User.Role.DEPT_HEAD],
                is_active=True,
            ).exclude(pk=u.pk).values('pk', 'username', 'first_name', 'last_name', 'role'))

        return render(request, 'leave/list.html', {
            'is_manager': is_manager,
            'is_md': u.role == User.Role.MD,
            'pending': pending,
            'history': history,
            'on_leave_today': on_leave_today,
            'today': today,
            'approvers': approvers,
        })


class LeaveCreateView(LoginRequiredMixin, View):
    def get(self, request):
        return render(request, 'leave/create.html', {
            'leave_types': LeaveRequest.LeaveType.choices,
        })

    def post(self, request):
        try:
            profile = request.user.employee_profile
        except EmployeeProfile.DoesNotExist:
            messages.error(request, _("No employee profile linked."))
            return redirect('leave:list')

        leave_type = request.POST.get('leave_type')
        start_date = request.POST.get('start_date')
        end_date = request.POST.get('end_date')
        reason = request.POST.get('reason', '')

        if not (leave_type and start_date and end_date):
            messages.error(request, _("All fields required."))
            return redirect('leave:create')

        # Quota enforcement (probation: 2 half-days/month, permanent: 4)
        try:
            sd = datetime.strptime(start_date, '%Y-%m-%d').date()
            ed = datetime.strptime(end_date, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            messages.error(request, _("Invalid date(s)."))
            return redirect('leave:create')

        if ed < sd:
            messages.error(request, _("End date must be on/after start date."))
            return redirect('leave:create')

        # Sum already-used half-days in this calendar month (approved+pending)
        same_month = LeaveRequest.objects.filter(
            profile=profile,
            start_date__year=sd.year,
            start_date__month=sd.month,
            status__in=[LeaveRequest.Status.PENDING, LeaveRequest.Status.APPROVED],
        )
        used = sum((_half_day_count(l) for l in same_month), Decimal('0'))

        # Provisional record (with parsed dates) to compute proposed usage.
        provisional = LeaveRequest(
            profile=profile, leave_type=leave_type,
            start_date=sd, end_date=ed,
        )
        proposed = used + _half_day_count(provisional)
        quota = _quota_for(profile)
        if proposed > quota:
            messages.error(
                request,
                _("Monthly leave quota exceeded: %(used)s / %(quota)s half-days. "
                  "Probation = 2 half-days/mo, Permanent = 4 half-days/mo.") %
                {'used': proposed, 'quota': quota},
            )
            return redirect('leave:create')

        leave = LeaveRequest.objects.create(
            profile=profile,
            leave_type=leave_type,
            start_date=start_date,
            end_date=end_date,
            reason=reason,
            status=LeaveRequest.Status.PENDING,
        )
        AuditLog.objects.create(
            profile=profile, performed_by=request.user,
            action=AuditLog.ActionType.LEAVE_REQUESTED,
            details={'pk': leave.pk, 'type': leave_type},
            ip_address=request.META.get('REMOTE_ADDR'),
        )

        # Email: notify reporting manager first, fall back to HR/MD
        mgr = profile.reporting_manager
        if mgr and mgr.user.email:
            approver_emails = [mgr.user.email]
        else:
            approver_emails = list(User.objects.filter(
                role__in=[User.Role.HR, User.Role.MD, User.Role.DEPT_HEAD],
                is_active=True,
            ).exclude(email='').values_list('email', flat=True))

        if approver_emails:
            send_html_mail(
                subject=_("[AEC HR] Leave request — %(name)s") % {
                    'name': profile.user.get_full_name()},
                template_name='email/leave_request.html',
                context={'leave': leave, 'profile': profile},
                to=approver_emails,
            )

        messages.success(request, _("Leave request submitted."))
        return redirect('leave:list')


class LeaveDecisionView(HROrMDMixin, View):
    def post(self, request, pk):
        leave = get_object_or_404(LeaveRequest, pk=pk)
        if leave.status != LeaveRequest.Status.PENDING:
            messages.warning(request, _("Already actioned."))
            return redirect('leave:list')

        action = request.POST.get('action')
        rejection_reason = request.POST.get('rejection_reason', '')

        if action == 'approve':
            leave.status = LeaveRequest.Status.APPROVED
            audit_action = AuditLog.ActionType.LEAVE_APPROVED
        elif action == 'reject':
            leave.status = LeaveRequest.Status.REJECTED
            leave.rejection_reason = rejection_reason
            audit_action = AuditLog.ActionType.LEAVE_REJECTED
        elif action == 'redirect':
            # Approval chain: redirect to a higher approver. Stays PENDING but
            # we tag the rejection_reason field with the redirect note so
            # the next approver can see who pushed it up.
            target_id = request.POST.get('redirect_to')
            target = User.objects.filter(pk=target_id).first()
            if not target:
                messages.error(request, _("Invalid redirect target."))
                return redirect('leave:list')
            leave.rejection_reason = (
                (leave.rejection_reason or '') +
                f"\n[Redirected by {request.user.username} -> {target.username} on "
                f"{timezone.now():%Y-%m-%d %H:%M}]"
            ).strip()
            leave.save()
            AuditLog.objects.create(
                profile=leave.profile, performed_by=request.user,
                action=AuditLog.ActionType.LEAVE_REQUESTED,
                details={'pk': leave.pk, 'redirected_to': target.username},
                ip_address=request.META.get('REMOTE_ADDR'),
            )
            if target.email:
                send_html_mail(
                    subject=_("[AEC HR] Leave needs your review — %(name)s") % {
                        'name': leave.profile.user.get_full_name()},
                    template_name='email/leave_request.html',
                    context={'leave': leave, 'profile': leave.profile},
                    to=[target.email],
                )
            messages.success(request, _("Leave redirected to %(u)s.") % {'u': target.username})
            return redirect('leave:list')
        else:
            messages.error(request, _("Invalid action."))
            return redirect('leave:list')

        leave.approved_by = request.user
        leave.save()

        AuditLog.objects.create(
            profile=leave.profile, performed_by=request.user,
            action=audit_action,
            details={'pk': leave.pk, 'status': leave.status},
            ip_address=request.META.get('REMOTE_ADDR'),
        )

        # Notify employee
        if leave.profile.user.email:
            send_html_mail(
                subject=_("[AEC HR] Leave %(status)s") % {'status': leave.get_status_display()},
                template_name='email/leave_decision.html',
                context={'leave': leave},
                to=[leave.profile.user.email],
            )

        messages.success(request, _("Leave %(status)s.") % {'status': leave.get_status_display()})
        return redirect('leave:list')


class LeaveCancelView(LoginRequiredMixin, View):
    def post(self, request, pk):
        leave = get_object_or_404(LeaveRequest, pk=pk)
        if leave.profile.user != request.user:
            messages.error(request, _("Cannot cancel another user's leave."))
            return redirect('leave:list')
        if leave.status != LeaveRequest.Status.PENDING:
            messages.warning(request, _("Cannot cancel an actioned leave."))
            return redirect('leave:list')
        leave.status = LeaveRequest.Status.CANCELLED
        leave.save()
        messages.success(request, _("Leave cancelled."))
        return redirect('leave:list')



# ────────────────────────── Calendar ──────────────────────────
class LeaveCalendarView(LoginRequiredMixin, View):
    """Month grid showing leaves + holidays."""
    def get(self, request):
        try:
            year = int(request.GET.get('year', timezone.now().year))
            month = int(request.GET.get('month', timezone.now().month))
        except (TypeError, ValueError):
            year, month = timezone.now().year, timezone.now().month

        from calendar import monthrange
        first = date(year, month, 1)
        _, last_day = monthrange(year, month)

        u = request.user
        is_manager = u.role in [User.Role.HR, User.Role.MD, User.Role.DEPT_HEAD]
        leaves_q = LeaveRequest.objects.filter(
            status__in=[LeaveRequest.Status.PENDING, LeaveRequest.Status.APPROVED],
            start_date__lte=date(year, month, last_day),
            end_date__gte=first,
        ).select_related('profile__user', 'profile__department')
        if not is_manager:
            try:
                leaves_q = leaves_q.filter(profile=u.employee_profile)
            except EmployeeProfile.DoesNotExist:
                leaves_q = leaves_q.none()

        holidays = list(Holiday.objects.filter(
            is_active=True, date__year=year, date__month=month,
        ))

        # Build day -> events mapping
        events_by_day = {d: {'leaves': [], 'holidays': []} for d in range(1, last_day + 1)}
        for h in holidays:
            events_by_day[h.date.day]['holidays'].append(h)
        for l in leaves_q:
            cur = max(l.start_date, first)
            until = min(l.end_date, date(year, month, last_day))
            while cur <= until:
                events_by_day[cur.day]['leaves'].append(l)
                cur = cur.fromordinal(cur.toordinal() + 1)

        # Flatten to a list ready for template iteration
        day_cells = [
            {
                'day': d,
                'holidays': events_by_day[d]['holidays'],
                'leaves': events_by_day[d]['leaves'],
            }
            for d in range(1, last_day + 1)
        ]

        # Compute week offset for first day
        first_weekday = first.weekday()  # 0=Mon
        return render(request, 'leave/calendar.html', {
            'year': year, 'month': month,
            'first_weekday': first_weekday,
            'first_weekday_range': range(first_weekday),
            'day_cells': day_cells,
            'is_manager': is_manager,
        })


# ────────────────────────── Holiday CRUD (HR) ──────────────────────────
class HROnly(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        u = self.request.user
        return u.is_authenticated and u.role in [User.Role.HR, User.Role.MD]


class HolidayListView(HROnly, View):
    def get(self, request):
        try:
            year = int(request.GET.get('year', timezone.now().year))
        except (TypeError, ValueError):
            year = timezone.now().year
        holidays = Holiday.objects.filter(date__year=year).order_by('date')
        return render(request, 'leave/holidays.html', {
            'year': year, 'holidays': holidays,
        })


class HolidayAddView(HROnly, View):
    def post(self, request):
        try:
            Holiday.objects.create(
                name=request.POST.get('name', '').strip() or 'Custom',
                date=request.POST.get('date'),
                is_public=False,
                is_active=True,
            )
            messages.success(request, _("Holiday added."))
        except Exception as e:
            messages.error(request, str(e))
        return redirect('leave:holidays')


class HolidayToggleView(HROnly, View):
    def post(self, request, pk):
        h = get_object_or_404(Holiday, pk=pk)
        h.is_active = not h.is_active
        h.save(update_fields=['is_active'])
        messages.success(request, _("Holiday updated."))
        return redirect('leave:holidays')


class HolidayDeleteView(HROnly, View):
    def post(self, request, pk):
        h = get_object_or_404(Holiday, pk=pk)
        h.delete()
        messages.success(request, _("Holiday deleted."))
        return redirect('leave:holidays')


class HolidayFetchView(HROnly, View):
    """Trigger holiday_fetch_kerala task on demand."""
    def post(self, request):
        from leave.tasks import holiday_fetch_kerala
        try:
            year = int(request.POST.get('year', timezone.now().year))
        except (TypeError, ValueError):
            year = timezone.now().year
        created = holiday_fetch_kerala(year)
        messages.success(request, _("%(c)s holidays fetched.") % {'c': created})
        return redirect('leave:holidays')
