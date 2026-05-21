"""
Assets / NOC / Discipline views.

- HR/MD: full CRUD on assets, issue NOC, manage discipline records.
- Staff: view own assets, upload signed NOC.
"""
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils.translation import gettext_lazy as _
from django.views import View

from core.models import AuditLog, EmployeeProfile, User
from .models import CompanyAsset, DisciplineRecord, NOC


class HROrMDMixin(LoginRequiredMixin, UserPassesTestMixin):
    def test_func(self):
        u = self.request.user
        return u.is_authenticated and u.role in [User.Role.HR, User.Role.MD]


class AssetsDashboardView(LoginRequiredMixin, View):
    def get(self, request):
        u = request.user
        is_manager = u.role in [User.Role.HR, User.Role.MD]
        if is_manager:
            assets = CompanyAsset.objects.select_related('profile__user').order_by('-issued_date')[:100]
            nocs = NOC.objects.select_related('profile__user').order_by('-created_at')[:50]
            employees = EmployeeProfile.objects.filter(is_active=True, probation_status__in=[EmployeeProfile.ProbationStatus.PROBATION, EmployeeProfile.ProbationStatus.PERMANENT]).select_related('user')
        else:
            try:
                profile = u.employee_profile
                assets = CompanyAsset.objects.filter(profile=profile).order_by('-issued_date')
                nocs = NOC.objects.filter(profile=profile).order_by('-created_at')
                employees = []
            except EmployeeProfile.DoesNotExist:
                assets, nocs, employees = [], [], []

        return render(request, 'assets/dashboard.html', {
            'is_manager': is_manager,
            'assets': assets,
            'nocs': nocs,
            'employees': employees,
            'asset_types': CompanyAsset.AssetType.choices,
        })


class AssetIssueView(HROrMDMixin, View):
    def post(self, request):
        try:
            profile = get_object_or_404(EmployeeProfile, pk=request.POST.get('profile_id'))
            asset = CompanyAsset.objects.create(
                profile=profile,
                asset_type=request.POST.get('asset_type'),
                label=request.POST.get('label', '').strip(),
                serial_no=request.POST.get('serial_no', '').strip(),
                issued_date=request.POST.get('issued_date'),
                notes=request.POST.get('notes', ''),
                issued_by=request.user,
            )
        except Exception as e:
            messages.error(request, _("Could not issue asset: %s") % e)
            return redirect('assets:dashboard')
        AuditLog.objects.create(
            profile=profile, performed_by=request.user,
            action=AuditLog.ActionType.PROFILE_UPDATED,
            details={'asset_id': asset.pk, 'asset_type': asset.asset_type, 'label': asset.label},
            ip_address=request.META.get('REMOTE_ADDR'),
        )
        messages.success(request, _("Asset issued."))
        return redirect('assets:dashboard')


class AssetReturnView(HROrMDMixin, View):
    def post(self, request, pk):
        from datetime import date
        asset = get_object_or_404(CompanyAsset, pk=pk)
        asset.status = request.POST.get('status') or CompanyAsset.Status.RETURNED
        asset.returned_date = date.today()
        asset.save()
        messages.success(request, _("Asset marked %(s)s.") % {'s': asset.get_status_display()})
        return redirect('assets:dashboard')


class NOCIssueView(HROrMDMixin, View):
    def post(self, request):
        profile = get_object_or_404(EmployeeProfile, pk=request.POST.get('profile_id'))
        noc = NOC.objects.create(
            profile=profile,
            purpose=request.POST.get('purpose', 'General'),
            template_pdf=request.FILES.get('template_pdf'),
            status=NOC.Status.ISSUED,
            issued_by=request.user,
            notes=request.POST.get('notes', ''),
        )
        messages.success(request, _("NOC issued (#%s).") % noc.pk)
        return redirect('assets:dashboard')


class NOCSignView(LoginRequiredMixin, View):
    """Employee uploads signed NOC PDF."""
    def post(self, request, pk):
        noc = get_object_or_404(NOC, pk=pk)
        if noc.profile.user != request.user and request.user.role not in [User.Role.HR, User.Role.MD]:
            messages.error(request, _("Access denied."))
            return redirect('assets:dashboard')
        if 'signed_pdf' in request.FILES:
            noc.signed_pdf = request.FILES['signed_pdf']
            noc.status = NOC.Status.SIGNED
            noc.save()
            messages.success(request, _("Signed copy uploaded."))
        return redirect('assets:dashboard')


class NOCTemplateDownloadView(LoginRequiredMixin, View):
    def get(self, request, pk):
        noc = get_object_or_404(NOC, pk=pk)
        if not noc.template_pdf:
            raise Http404("No template uploaded")
        return FileResponse(noc.template_pdf.open('rb'),
                            as_attachment=True,
                            filename=f"NOC_{noc.pk}_template.pdf")


class DisciplineListView(HROrMDMixin, View):
    def get(self, request):
        records = DisciplineRecord.objects.select_related(
            'profile__user', 'profile__department'
        ).order_by('-occurred_on')[:200]
        return render(request, 'assets/discipline.html', {'records': records})


class DisciplineRevokeView(HROrMDMixin, View):
    def post(self, request, pk):
        rec = get_object_or_404(DisciplineRecord, pk=pk)
        rec.is_active = not rec.is_active
        rec.save(update_fields=['is_active'])
        messages.success(request, _("Discipline record updated."))
        return redirect('assets:discipline')
