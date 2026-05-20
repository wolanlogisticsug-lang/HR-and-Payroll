"""
Payroll views.

Permissions:
- MD/HR        -> generate, approve, view all, edit incentives (MD-only).
- Dept Head    -> view (read-only) own dept after generation, 48h review window.
- Staff        -> view & download own payslips only.
"""
from datetime import date
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.http import HttpResponse, HttpResponseForbidden, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View

from core.models import (
    AuditLog,
    Department,
    EmployeeProfile,
    Incentive,
    Payroll,
    User,
)
from twofa.emails import send_html_mail
from .pdf import build_payslip_pdf # Reload forced 2026-05-13
from .service import (
    KERALA_PT_SLABS,
    PayrollService,
    generate_for_month,
    generate_for_profile,
)


# ────────────────────────── Mixins ──────────────────────────
class HRorMDRequiredMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        u = self.request.user
        return u.is_authenticated and u.role in [User.Role.HR, User.Role.MD]


class MDOnlyMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        u = self.request.user
        return u.is_authenticated and u.role == User.Role.MD


# ────────────────────────── Dashboard ──────────────────────────
class PayrollDashboardView(LoginRequiredMixin, View):
    """Main payroll page.
    - MD/HR: month selector, list all payrolls, incentives editor (MD only),
             pay history Chart.js.
    - Staff: own pay history + slip download links.
    """
    def get(self, request):
        u = request.user
        today = date.today()
        try:
            year = int(request.GET.get('year', today.year))
            month = int(request.GET.get('month', today.month))
        except (TypeError, ValueError):
            year, month = today.year, today.month

        is_manager = u.role in [User.Role.HR, User.Role.MD]
        is_md = u.role == User.Role.MD

        # Department filter (managers only)
        dept_filter = request.GET.get('dept_filter', '')

        if is_manager:
            payrolls_qs = Payroll.objects.filter(
                month__year=year, month__month=month
            ).select_related('profile__user', 'profile__department').order_by(
                'profile__department__name', 'profile__employee_id'
            )
            if dept_filter:
                payrolls_qs = payrolls_qs.filter(profile__department_id=dept_filter)

            payrolls = payrolls_qs

            incentives = Incentive.objects.filter(
                month__year=year, month__month=month
            ).select_related('profile__user', 'created_by').order_by('-created_at')
            employees = EmployeeProfile.objects.filter(is_active=True).select_related('user', 'department')
            history_qs = Payroll.objects.filter(status__in=[
                Payroll.Status.HR_APPROVED, Payroll.Status.FINALIZED
            ]).order_by('month')

            # Build department groups for template
            from collections import OrderedDict
            dept_groups = OrderedDict()
            for p in payrolls:
                dept_name = p.profile.department.name if p.profile.department else 'Unassigned'
                dept_obj = p.profile.department
                if dept_name not in dept_groups:
                    dept_groups[dept_name] = {'dept': dept_obj, 'payrolls': [], 'total_net': Decimal('0')}
                dept_groups[dept_name]['payrolls'].append(p)
                dept_groups[dept_name]['total_net'] += Decimal(p.net_salary)

            departments = Department.objects.filter(is_active=True).order_by('name')
        else:
            # Robust fetch by email for staff to handle multi-account confusion
            base_qs = Payroll.objects.filter(
                profile__user__email=u.email
            ).select_related('profile__user', 'profile__department').order_by('-month')

            payrolls = base_qs[:12]

            incentives = Incentive.objects.filter(
                profile__user__email=u.email
            ).select_related('profile__user').order_by('-month')[:12]

            employees = []
            dept_groups = {}
            departments = []
            history_qs = base_qs.filter(status__in=[Payroll.Status.HR_APPROVED, Payroll.Status.FINALIZED])

        # Aggregate Chart.js data: total net by month
        history_map = {}
        for p in history_qs:
            key = p.month.strftime('%Y-%m')
            history_map[key] = history_map.get(key, Decimal('0')) + Decimal(p.net_salary)
        history_labels = sorted(history_map.keys())
        history_values = [float(history_map[k]) for k in history_labels]

        return render(request, 'payroll/dashboard.html', {
            'is_manager': is_manager,
            'is_md': is_md,
            'year': year,
            'month': month,
            'payrolls': payrolls,
            'dept_groups': dept_groups,
            'departments': departments,
            'dept_filter': dept_filter,
            'incentives': incentives,
            'employees': employees,
            'history_labels': history_labels,
            'history_values': history_values,
            'incentive_types': Incentive.IncentiveType.choices,
        })


# ────────────────────────── Generate ──────────────────────────
class ManualAdjustmentsView(HRorMDRequiredMixin, View):
    """Admin Dashboard > Payroll > Manual Adjustments
    Select Department -> Enter OT/Incentives -> Submit locks data and generates payroll for that department.
    """
    def get(self, request):
        today = date.today()
        year = int(request.GET.get('year', today.year))
        month = int(request.GET.get('month', today.month))
        dept_id = request.GET.get('department_id')
        
        departments = Department.objects.filter(is_active=True).order_by('name')
        employees_data = []
        selected_dept_name = ""
        if dept_id:
            dept = get_object_or_404(Department, id=dept_id)
            selected_dept_name = dept.name
            profiles = dept.employees.filter(is_active=True)
            for p in profiles:
                svc = PayrollService(p, year, month)
                computed_ot = svc.get_ot_hours()
                employees_data.append({
                    'profile': p,
                    'computed_ot': computed_ot
                })
                
        return render(request, 'payroll/manual_adjustments.html', {
            'year': year, 'month': month,
            'departments': departments,
            'selected_dept': int(dept_id) if dept_id else None,
            'selected_dept_name': selected_dept_name,
            'employees_data': employees_data,
        })
        
    def post(self, request):
        year = int(request.POST.get('year'))
        month = int(request.POST.get('month'))
        dept_id = request.POST.get('department_id')
        dept = get_object_or_404(Department, id=dept_id)
        
        created = []
        for profile in dept.employees.filter(is_active=True):
            pid = str(profile.id)
            ot = request.POST.get(f'ot_{pid}')
            inc = request.POST.get(f'incentive_{pid}')
            
            # Add Incentive if provided
            if inc and float(inc) > 0:
                Incentive.objects.create(
                    profile=profile, month=date(year, month, 1),
                    amount=Decimal(inc), incentive_type='CUSTOM',
                    description='Manual Entry before Payroll Generation',
                    created_by=request.user
                )
                
            ot_override = Decimal(ot) if ot and float(ot) > 0 else None
            
            payroll = generate_for_profile(profile, year, month, ot_override=ot_override)
            created.append(payroll)
            
        messages.success(request, f"Generated {len(created)} payroll drafts for {dept.name} ({month:02d}/{year}).")
        return redirect(f"{reverse_lazy('payroll:dashboard')}?year={year}&month={month}")


# ────────────────────────── Approve ──────────────────────────
class ApproveView(HRorMDRequiredMixin, View):
    """HR/MD approves a single payroll draft."""
    def post(self, request, pk):
        payroll = get_object_or_404(Payroll, pk=pk)
        if payroll.is_locked:
            messages.warning(request, "Payroll already finalized.")
            return redirect(self._dash_url(payroll))

        action = request.POST.get('action', 'approve')
        if action == 'approve':
            payroll.status = Payroll.Status.HR_APPROVED
            payroll.reviewed_by = request.user
        elif action == 'finalize':
            payroll.status = Payroll.Status.FINALIZED
            payroll.is_locked = True
            payroll.finalized_at = timezone.now()
            payroll.reviewed_by = request.user
        payroll.save()

        AuditLog.objects.create(
            profile=payroll.profile,
            performed_by=request.user,
            action=(AuditLog.ActionType.PAYROLL_FINALIZED
                    if action == 'finalize' else AuditLog.ActionType.PAYROLL_GENERATED),
            details={'status': payroll.status, 'pk': payroll.pk},
            ip_address=request.META.get('REMOTE_ADDR'),
        )
        messages.success(request, f"Payroll {action}d.")
        return redirect(self._dash_url(payroll))

    def _dash_url(self, payroll):
        return (f"{reverse_lazy('payroll:dashboard')}"
                f"?year={payroll.month.year}&month={payroll.month.month}")


# ────────────────────────── Slip (PDF) ──────────────────────────
class SlipView(LoginRequiredMixin, View):
    def get(self, request, year, month):
        u = request.user
        # Determine which profile's slip
        profile_id = request.GET.get('profile_id')
        if profile_id and u.role in [User.Role.HR, User.Role.MD]:
            profile = get_object_or_404(EmployeeProfile, pk=profile_id)
        else:
            from django.db.models import F
            profile = EmployeeProfile.objects.filter(
                user__email=u.email
            ).order_by(
                F('date_of_joining').desc(nulls_last=True),
                F('designation').desc(nulls_last=True),
                '-id'
            ).first()
            
            if not profile:
                raise Http404("No employee profile found for your account.")

        payroll = Payroll.objects.filter(
            profile__user__email=u.email, month__year=year, month__month=month
        ).order_by('-id').first()
        if not payroll:
            raise Http404("Payslip not generated for this month.")
        if (u.role == User.Role.STAFF
                and payroll.status not in [Payroll.Status.HR_APPROVED, Payroll.Status.FINALIZED]):
            return HttpResponseForbidden("Payslip not yet approved.")

        pdf_data = build_payslip_pdf(payroll)
        resp = HttpResponse(pdf_data, content_type='application/pdf')
        fname = f"payslip_{profile.employee_id}_{year}_{month:02d}.pdf"
        resp['Content-Disposition'] = f'attachment; filename="{fname}"'
        return resp


# ────────────────────────── Tax page ──────────────────────────
class TaxPageView(HRorMDRequiredMixin, View):
    """Tracks municipal/building/stationery payments — read-only list with
    sample seed entries (replace with model later)."""
    def get(self, request):
        # Summary cards from existing payrolls
        latest_payrolls = Payroll.objects.order_by('-month')[:50]
        total_pt = sum((Decimal(p.pt_deduction) for p in latest_payrolls), Decimal('0'))
        total_esi = sum((Decimal(p.esi_deduction) for p in latest_payrolls), Decimal('0'))
        total_pf = sum((Decimal(p.pf_deduction) for p in latest_payrolls), Decimal('0'))

        return render(request, 'payroll/tax.html', {
            'kerala_pt_slabs': KERALA_PT_SLABS,
            'total_pt': total_pt,
            'total_esi': total_esi,
            'total_pf': total_pf,
        })


# ────────────────────────── Incentive CRUD (MD only) ──────────────────────────
class IncentiveAddView(MDOnlyMixin, View):
    def post(self, request):
        try:
            profile = get_object_or_404(EmployeeProfile, pk=request.POST.get('profile_id'))
            incentive_type = request.POST.get('incentive_type')
            amount = Decimal(request.POST.get('amount') or '0')
            description = request.POST.get('description', '')
            visuals_pct = Decimal(request.POST.get('visuals_pct') or '0')
            year = int(request.POST.get('year'))
            month = int(request.POST.get('month'))
        except Exception as e:
            messages.error(request, f"Invalid input: {e}")
            return redirect('payroll:dashboard')

        Incentive.objects.create(
            profile=profile,
            incentive_type=incentive_type,
            amount=amount,
            description=description,
            visuals_pct=visuals_pct,
            month=date(year, month, 1),
            created_by=request.user,
        )
        AuditLog.objects.create(
            profile=profile, performed_by=request.user,
            action=AuditLog.ActionType.INCENTIVE_ADDED,
            details={'amount': str(amount), 'type': incentive_type},
            ip_address=request.META.get('REMOTE_ADDR'),
        )
        messages.success(request, f"Incentive added for {profile.employee_id}.")
        return redirect(f"{reverse_lazy('payroll:dashboard')}?year={year}&month={month}")


class IncentiveDeleteView(MDOnlyMixin, View):
    def post(self, request, pk):
        inc = get_object_or_404(Incentive, pk=pk)
        year, month = inc.month.year, inc.month.month
        inc.delete()
        messages.success(request, "Incentive removed.")
        return redirect(f"{reverse_lazy('payroll:dashboard')}?year={year}&month={month}")
