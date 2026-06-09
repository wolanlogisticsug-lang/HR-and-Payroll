from django.shortcuts import render, redirect
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.db.models import F
from decimal import Decimal

from core.models import User, Department, EmployeeProfile, ReimbursementRequest, StaffTask
from notifications.models import Notification
from core.biometrics.services import AttendanceBiometricSyncService

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import generics, status
from rest_framework.serializers import ModelSerializer


# Inline serializer - no external dependency needed
class BiometricDeviceSerializer(ModelSerializer):
    class Meta:
        # Uses a plain dict response since no device model exists yet
        pass


def setup_owner(request):
    if User.objects.exists():
        return redirect('login')
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        email = request.POST.get('email')
        first_name = request.POST.get('first_name')
        if username and password:
            user = User.objects.create_user(
                username=username, password=password,
                email=email, first_name=first_name,
                role=User.Role.MD, is_superuser=True, is_staff=True
            )
            dept, _ = Department.objects.get_or_create(
                name='Wolan HR Enclave OPC Pvt Ltd',
                defaults={'code': 'ENCLAVE', 'is_active': True}
            )
            EmployeeProfile.objects.create(
                user=user, department=dept,
                probation_status=EmployeeProfile.ProbationStatus.PERMANENT
            )
            login(request, user)
            return redirect('dashboard')
    return render(request, 'registration/setup.html')


def signup(request):
    return redirect('login')


@login_required
def reimbursements_view(request):
    context = {}
    u = request.user
    today = timezone.now().date()
    my_profile = EmployeeProfile.objects.filter(
        user__email=u.email
    ).select_related('reporting_manager__user', 'department').order_by(
        F('date_of_joining').desc(nulls_last=True),
        F('designation').desc(nulls_last=True), '-id'
    ).first()
    if not my_profile and not u.is_superuser:
        dept, _ = Department.objects.get_or_create(
            name="HR & Administration" if u.role == 'HR' else "General"
        )
        my_profile = EmployeeProfile.objects.create(
            user=u, department=dept,
            designation="HR Administrator" if u.role == 'HR' else "Staff",
            basic_salary=Decimal('40000'),
            is_active=True, is_locked=True, probation_status='PERMANENT',
        )
    context['my_profile'] = my_profile
    if request.method == 'POST':
        pass
    context['departments'] = Department.objects.filter(is_active=True).order_by('name')
    context['dept_reimbursements'] = []
    context['today'] = today
    return render(request, 'reimbursements.html', context)


@login_required
def tasks_view(request):
    context = {}
    return render(request, 'tasks.html', context)


class BiometricDeviceListCreateAPIView(APIView):
    def get(self, request):
        return Response(
            {"message": "Biometric devices endpoint ready.", "devices": []},
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        return Response(
            {"message": "Device registered."},
            status=status.HTTP_201_CREATED,
        )


class BiometricSyncExecutionAPIView(APIView):
    def post(self, request, *args, **kwargs):
        service = AttendanceBiometricSyncService()
        report = service.sync_all()
        return Response(
            {"message": "Biometric sync complete.", "report": report},
            status=status.HTTP_200_OK,
        )