"""
wolan Hr HR Super App — Admin Configuration
"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DefaultUserAdmin
from .models import (
    User, Department, EmployeeProfile, Attendance,
    LeaveRequest, Incentive, Payroll, AuditLog, Holiday
)

@admin.register(User)
class UserAdmin(DefaultUserAdmin):
    list_display = ('username', 'email', 'first_name', 'last_name', 'role', 'is_staff')
    list_filter = ('role', 'is_staff', 'is_active')
    fieldsets = DefaultUserAdmin.fieldsets + (
        ('wolan Hr Custom Fields', {'fields': ('role', 'phone', 'date_of_birth', 'profile_picture')}),
    )

@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = ('name', 'code', 'head', 'is_cinema', 'is_active')
    search_fields = ('name', 'code')
    list_filter = ('is_cinema', 'is_active')

@admin.register(EmployeeProfile)
class EmployeeProfileAdmin(admin.ModelAdmin):
    list_display = ('employee_id', 'user', 'department', 'designation', 'probation_status', 'is_locked')
    search_fields = ('employee_id', 'user__first_name', 'user__last_name', 'user__email')
    list_filter = ('probation_status', 'is_locked', 'department', 'is_active')

@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ('profile', 'date', 'in_time', 'out_time', 'source', 'is_valid', 'is_late')
    list_filter = ('date', 'source', 'is_valid', 'is_late')
    search_fields = ('profile__employee_id', 'profile__user__first_name')
    date_hierarchy = 'date'

@admin.register(LeaveRequest)
class LeaveRequestAdmin(admin.ModelAdmin):
    list_display = ('profile', 'leave_type', 'start_date', 'end_date', 'status')
    list_filter = ('status', 'leave_type', 'start_date')
    search_fields = ('profile__employee_id',)

@admin.register(Incentive)
class IncentiveAdmin(admin.ModelAdmin):
    list_display = ('profile', 'incentive_type', 'amount', 'month', 'created_by')
    list_filter = ('incentive_type', 'month')
    search_fields = ('profile__employee_id',)

@admin.register(Payroll)
class PayrollAdmin(admin.ModelAdmin):
    list_display = ('profile', 'month', 'net_salary', 'status', 'is_locked')
    list_filter = ('status', 'month', 'is_locked')
    search_fields = ('profile__employee_id',)

@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'action', 'performed_by', 'profile', 'ip_address')
    list_filter = ('action', 'timestamp')
    search_fields = ('performed_by__username', 'profile__employee_id')
    readonly_fields = ('profile', 'performed_by', 'action', 'details', 'ip_address', 'timestamp')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

@admin.register(Holiday)
class HolidayAdmin(admin.ModelAdmin):
    list_display = ('name', 'date', 'is_public', 'is_active')
    list_filter = ('is_public', 'is_active', 'date')
    search_fields = ('name',)
