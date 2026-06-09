"""
wolan Hr HR Super App — Core Models
All foundational models: User, Department, EmployeeProfile,
Attendance, LeaveRequest, Incentive, Payroll, AuditLog.
"""
import uuid
from decimal import Decimal
from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils import timezone


# ──────────────────────────────────────────────────────────────
# 1. Custom User (RBAC roles)
# ──────────────────────────────────────────────────────────────
class User(AbstractUser):
    """Extended user with RBAC role. MD sits at top of hierarchy."""

    class Role(models.TextChoices):
        MD = 'MD', 'Managing Director'
        GM = 'GM', 'General Manager'
        HR = 'HR', 'Human Resources'
        DEPT_HEAD = 'DEPT_HEAD', 'Department Head'
        STAFF = 'STAFF', 'Staff'

    role = models.CharField(
        max_length=20,
        choices=Role.choices,
        default=Role.STAFF,
    )
    phone = models.CharField(max_length=15, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    profile_picture = models.ImageField(
        upload_to='profile_pics/%Y/%m/', blank=True, null=True
    )

    class Meta:
        db_table = 'core_user'
        ordering = ['first_name', 'last_name']

    def __str__(self):
        return f"{self.get_full_name()} ({self.get_role_display()})"

    @property
    def is_md(self):
        return self.role == self.Role.MD

    @property
    def is_gm(self):
        return self.role == self.Role.GM

    @property
    def is_hr(self):
        return self.role == self.Role.HR

    @property
    def is_dept_head(self):
        return self.role == self.Role.DEPT_HEAD


# ──────────────────────────────────────────────────────────────
# 2. Department
# ──────────────────────────────────────────────────────────────
class Department(models.Model):
    """
    wolan Hr business unit. Each has geofence coords and custom
    work-day configuration. Cinema/Residency include Sundays.
    """
    DEFAULT_WORK_DAYS = [0, 1, 2, 3, 4, 5]  # Mon-Sat

    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=20, unique=True)
    description = models.TextField(blank=True)

    # Geofence
    latitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        help_text='Department center latitude for GPS geofence'
    )
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True,
        help_text='Department center longitude for GPS geofence'
    )

    # Cinema-specific: exempt from late penalties
    is_cinema = models.BooleanField(
        default=False,
        help_text='Cinema departments are exempt from late penalties'
    )

    # Work days as comma-separated integers (0=Mon, 6=Sun)
    work_days = models.CharField(
        max_length=50,
        default='0,1,2,3,4,5',
        help_text='Comma-separated work days: 0=Mon,1=Tue,...,6=Sun'
    )

    # Allowed IPs for desktop attendance (comma-separated)
    allowed_ips = models.TextField(
        blank=True,
        help_text='Comma-separated IP addresses for desktop attendance'
    )

    head = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='headed_departments',
        limit_choices_to={'role__in': ['MD', 'GM', 'DEPT_HEAD']},
    )

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'core_department'
        ordering = ['name']

    def __str__(self):
        return self.name

    def get_work_days_list(self):
        """Return work days as list of integers."""
        return [int(d.strip()) for d in self.work_days.split(',') if d.strip()]


# ──────────────────────────────────────────────────────────────
# 3. Employee Profile
# ──────────────────────────────────────────────────────────────
class EmployeeProfile(models.Model):
    """
    Core employee record linked 1:1 to User. Dual bank accounts,
    document vault, lock mechanism for verified profiles.
    """

    class ProbationStatus(models.TextChoices):
        PROBATION = 'PROBATION', 'Probation'
        PERMANENT = 'PERMANENT', 'Permanent'
        TERMINATED = 'TERMINATED', 'Terminated'
        TRAINEE = 'TRAINEE', 'Trainee'
        INTERN = 'INTERN', 'Intern'

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='employee_profile',
    )
    employee_id = models.CharField(
        max_length=20, unique=True, blank=True,
        help_text='Auto-generated employee ID (e.g., wolan Hr-CIN-001)'
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name='employees',
    )

    # Dual bank accounts
    personal_account = models.CharField(
        max_length=30, blank=True,
        help_text='Personal bank account (probation salary)'
    )
    salary_account = models.CharField(
        max_length=30, blank=True,
        help_text='Salary bank account (permanent salary)'
    )

    # Document vault (JSON: {doc_type: {url, verified, uploaded_at}})
    docs_vault = models.JSONField(
        default=dict, blank=True,
        help_text='Document storage: academic, ID, experience, salary slips, photo'
    )

    # Lock profile after HR verification
    is_locked = models.BooleanField(
        default=False,
        help_text='Locked after HR verification — no re-upload allowed'
    )

    probation_status = models.CharField(
        max_length=20,
        choices=ProbationStatus.choices,
        default=ProbationStatus.PROBATION,
    )
    
    reporting_manager = models.ForeignKey(
        'self',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='team_members',
        help_text='Manager responsible for leave approvals and performance reviews'
    )
    
    # Onboarding and Lifecycle
    onboarding_status = models.CharField(
        max_length=20,
        choices=[('PENDING', 'Pending'), ('VERIFIED', 'Verified'), ('REJECTED', 'Rejected')],
        default='PENDING',
    )
    rejection_reason = models.CharField(max_length=255, blank=True)
    probation_end_date = models.DateField(null=True, blank=True)

    # Aadhaar: stored MASKED only (XXXXXXXX1234)
    aadhaar_masked = models.CharField(
        max_length=12, blank=True,
        help_text='Masked Aadhaar: XXXXXXXX1234 format only'
    )

    date_of_joining = models.DateField(null=True, blank=True)
    notice_period_days = models.IntegerField(
        default=30,
        help_text='Hardcoded 1-month notice for all employees'
    )
    designation = models.CharField(max_length=100, blank=True)
    basic_salary = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal('0.00'),
        help_text='Monthly basic salary'
    )

    emergency_contact = models.CharField(max_length=15, blank=True)
    address = models.TextField(blank=True)

    # Personal Details
    wedding_anniversary = models.DateField(null=True, blank=True, help_text='Wedding anniversary date')
    spouse_name = models.CharField(max_length=100, blank=True)
    blood_group = models.CharField(max_length=20, blank=True)
    hobbies = models.TextField(blank=True)

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'core_employee_profile'
        ordering = ['employee_id']
        indexes = [
            models.Index(fields=['department', 'probation_status']),
            models.Index(fields=['is_active', 'department']),
        ]

    def __str__(self):
        return f"{self.employee_id} — {self.user.get_full_name()}"

    @property
    def daily_rate(self):
        """Salary / 30 (fixed divisor, ignoring actual month length)."""
        return self.basic_salary / Decimal('30')

    def save(self, *args, **kwargs):
        if not self.employee_id:
            self.employee_id = self._generate_employee_id()
        super().save(*args, **kwargs)

    def _generate_employee_id(self):
        dept_code = self.department.code if self.department else 'GEN'
        count = EmployeeProfile.objects.filter(
            department=self.department
        ).count() + 1
        return f"wolan Hr-{dept_code}-{count:03d}"


# ──────────────────────────────────────────────────────────────
# 4. Attendance
# ──────────────────────────────────────────────────────────────
class Attendance(models.Model):
    """
    Daily clock in/out. GPS geofence for mobile,
    IP + face capture for desktop.
    """
    profile = models.ForeignKey(
        EmployeeProfile,
        on_delete=models.PROTECT,
        related_name='attendance_records',
    )
    date = models.DateField(default=timezone.now)
    in_time = models.DateTimeField(null=True, blank=True)
    out_time = models.DateTimeField(null=True, blank=True)

    # GPS coordinates (stored as decimals)
    gps_latitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )
    gps_longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )

    ip_address = models.GenericIPAddressField(null=True, blank=True)

    # Human-readable location label (department name / office)
    location_name = models.CharField(
        max_length=200, blank=True,
        help_text='Location name at time of check-in (department / office)'
    )

    # Face capture image path (no biometrics stored)
    face_image_path = models.CharField(
        max_length=500, blank=True,
        help_text='Path to face capture image (webcam verification)'
    )

    is_valid = models.BooleanField(
        default=True,
        help_text='False if geofence/IP validation failed'
    )
    is_late = models.BooleanField(default=False)
    late_minutes = models.IntegerField(default=0)

    # Source of clock-in
    class ClockSource(models.TextChoices):
        MOBILE = 'MOBILE', 'Mobile (GPS)'
        DESKTOP = 'DESKTOP', 'Desktop (IP+Face)'
        MANUAL = 'MANUAL', 'Manual Entry'

    source = models.CharField(
        max_length=10,
        choices=ClockSource.choices,
        default=ClockSource.MOBILE,
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'core_attendance'
        ordering = ['-date', '-in_time']
        unique_together = ['profile', 'date']
        indexes = [
            models.Index(fields=['date', 'profile']),
            models.Index(fields=['profile', '-in_time']),
            models.Index(fields=['is_late', 'date']),
        ]

    def __str__(self):
        return f"{self.profile.employee_id} — {self.date}"

    @property
    def hours_worked(self):
        if self.in_time and self.out_time:
            delta = self.out_time - self.in_time
            return round(delta.total_seconds() / 3600, 2)
        return 0


# ──────────────────────────────────────────────────────────────
# 5. Leave Request
# ──────────────────────────────────────────────────────────────
class LeaveRequest(models.Model):
    """
    Leave management. Probation: 1/mo (2 half-days).
    Permanent: 2/mo (4 half-days).
    """

    class LeaveType(models.TextChoices):
        FULL_DAY = 'FULL', 'Full Day'
        HALF_DAY = 'HALF', 'Half Day'
        CASUAL = 'CASUAL', 'Casual Leave'
        EMERGENCY = 'EMERGENCY', 'Emergency'

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        APPROVED = 'APPROVED', 'Approved'
        REJECTED = 'REJECTED', 'Rejected'
        CANCELLED = 'CANCELLED', 'Cancelled'

    profile = models.ForeignKey(
        EmployeeProfile,
        on_delete=models.PROTECT,
        related_name='leave_requests',
    )
    leave_type = models.CharField(
        max_length=20, choices=LeaveType.choices
    )
    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='approved_leaves',
    )
    rejection_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'core_leave_request'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.profile.employee_id} | {self.leave_type} | {self.start_date}"

    @property
    def duration_days(self):
        return (self.end_date - self.start_date).days + 1


# ──────────────────────────────────────────────────────────────
# 6. Incentive (MD-only)
# ──────────────────────────────────────────────────────────────
class Incentive(models.Model):
    """
    MD-only table. Per-employee incentives: project in-house/client,
    orders volume, weekend sales. Visual % + Final Amount.
    """

    class IncentiveType(models.TextChoices):
        PROJECT_INHOUSE = 'PROJECT_INHOUSE', 'Project In-House'
        PROJECT_CLIENT = 'PROJECT_CLIENT', 'Project Client'
        WEEKEND_SAT = 'WEEKEND_SAT', 'Weekend Sales (Saturday)'
        WEEKEND_SUN = 'WEEKEND_SUN', 'Weekend Sales (Sunday)'
        ORDERS_VOLUME = 'ORDERS_VOLUME', 'Orders Volume'
        CUSTOM = 'CUSTOM', 'Custom'

    profile = models.ForeignKey(
        EmployeeProfile,
        on_delete=models.PROTECT,
        related_name='incentives',
    )
    incentive_type = models.CharField(
        max_length=30, choices=IncentiveType.choices
    )
    amount = models.DecimalField(
        max_digits=10, decimal_places=2,
        validators=[MinValueValidator(Decimal('0.00'))],
    )
    description = models.TextField(blank=True)
    visuals_pct = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('0.00'),
        help_text='Percentage visual indicator'
    )
    month = models.DateField(
        help_text='Month this incentive applies to (1st of month)'
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='created_incentives',
        limit_choices_to={'role': 'MD'},
        help_text='Only MD can create incentives'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'core_incentive'
        ordering = ['-month', 'profile']

    def __str__(self):
        return f"{self.profile.employee_id} | ₹{self.amount} | {self.get_incentive_type_display()}"


# ──────────────────────────────────────────────────────────────
# 7. Payroll
# ──────────────────────────────────────────────────────────────
class Payroll(models.Model):
    """
    Monthly payroll. daily = salary/30. OT = hrs * 2 * daily.
    End-month auto-gen → Heads 48h review → HR finalize.
    """

    class Status(models.TextChoices):
        DRAFT = 'DRAFT', 'Draft'
        HEAD_REVIEW = 'HEAD_REVIEW', 'Head Review (48h)'
        HR_APPROVED = 'HR_APPROVED', 'HR Approved'
        FINALIZED = 'FINALIZED', 'Finalized'

    profile = models.ForeignKey(
        EmployeeProfile,
        on_delete=models.PROTECT,
        related_name='payroll_records',
    )
    month = models.DateField(
        help_text='Payroll month (1st of month)'
    )
    # Computed fields
    basic_salary = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    daily_rate = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    working_days = models.IntegerField(default=0)
    days_present = models.IntegerField(default=0)
    days_absent = models.IntegerField(default=0)
    late_deduction_days = models.DecimalField(max_digits=5, decimal_places=1, default=Decimal('0.0'))

    # Overtime
    ot_hours = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal('0.00'))
    ot_amount = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))

    # Incentive total (summed from Incentive table)
    incentive_total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))

    # Deductions
    pt_deduction = models.DecimalField(
        max_digits=8, decimal_places=2, default=Decimal('0.00'),
        help_text='Kerala Professional Tax slab'
    )
    esi_deduction = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('0.00'))
    pf_deduction = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('0.00'))
    other_deductions = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal('0.00'))
    deduction_notes = models.TextField(blank=True)

    # Totals
    gross_salary = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    total_deductions = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))
    net_salary = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal('0.00'))

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    is_locked = models.BooleanField(
        default=False,
        help_text='Immutable once locked/finalized'
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='reviewed_payrolls',
    )
    finalized_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'core_payroll'
        unique_together = ['profile', 'month']
        ordering = ['-month']

    def __str__(self):
        return f"{self.profile.employee_id} | {self.month.strftime('%b %Y')} | ₹{self.net_salary}"


# ──────────────────────────────────────────────────────────────
# 8. Audit Log (Immutable)
# ──────────────────────────────────────────────────────────────
class AuditLog(models.Model):
    """
    Immutable audit trail. No updates or deletes allowed.
    Tracks all critical actions across the system.
    """

    class ActionType(models.TextChoices):
        PROFILE_CREATED = 'PROFILE_CREATED', 'Profile Created'
        PROFILE_LOCKED = 'PROFILE_LOCKED', 'Profile Locked'
        PROFILE_UPDATED = 'PROFILE_UPDATED', 'Profile Updated'
        DOC_UPLOADED = 'DOC_UPLOADED', 'Document Uploaded'
        DOC_VERIFIED = 'DOC_VERIFIED', 'Document Verified'
        ATTENDANCE_IN = 'ATTENDANCE_IN', 'Clock In'
        ATTENDANCE_OUT = 'ATTENDANCE_OUT', 'Clock Out'
        LEAVE_REQUESTED = 'LEAVE_REQUESTED', 'Leave Requested'
        LEAVE_APPROVED = 'LEAVE_APPROVED', 'Leave Approved'
        LEAVE_REJECTED = 'LEAVE_REJECTED', 'Leave Rejected'
        INCENTIVE_ADDED = 'INCENTIVE_ADDED', 'Incentive Added'
        PAYROLL_GENERATED = 'PAYROLL_GENERATED', 'Payroll Generated'
        PAYROLL_FINALIZED = 'PAYROLL_FINALIZED', 'Payroll Finalized'
        SALARY_CHANGED = 'SALARY_CHANGED', 'Salary Changed'
        STATUS_CHANGED = 'STATUS_CHANGED', 'Status Changed'
        TERMINATED = 'TERMINATED', 'Terminated'
        LOGIN = 'LOGIN', 'User Login'
        LOGOUT = 'LOGOUT', 'User Logout'

    profile = models.ForeignKey(
        EmployeeProfile,
        on_delete=models.PROTECT,
        related_name='audit_logs',
        null=True, blank=True,
    )
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='audit_actions',
    )
    action = models.CharField(max_length=30, choices=ActionType.choices)
    details = models.JSONField(
        default=dict, blank=True,
        help_text='Additional action details as JSON'
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'core_audit_log'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['-timestamp']),
            models.Index(fields=['profile', '-timestamp']),
            models.Index(fields=['action', '-timestamp']),
        ]
        # Prevent updates/deletes at DB level via app logic
        managed = True

    def __str__(self):
        return f"[{self.timestamp}] {self.action} by {self.performed_by}"

    def save(self, *args, **kwargs):
        # Enforce immutability: only allow creation
        if self.pk:
            raise ValueError("AuditLog records are immutable — cannot update.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("AuditLog records are immutable — cannot delete.")


# ──────────────────────────────────────────────────────────────
# 9. Holiday Calendar
# ──────────────────────────────────────────────────────────────
class Holiday(models.Model):
    """
    Kerala public holidays with HR edit capability.
    Auto-fetched + manually adjustable.
    """
    name = models.CharField(max_length=200)
    date = models.DateField()
    is_public = models.BooleanField(
        default=True,
        help_text='Public holiday (auto-fetched) vs custom'
    )
    is_active = models.BooleanField(
        default=True,
        help_text='HR can deactivate holidays (e.g., remove Buddha Purnima)'
    )
    departments = models.ManyToManyField(
        Department, blank=True,
        help_text='If empty, applies to all departments'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'core_holiday'
        ordering = ['date']
        unique_together = ['name', 'date']

    def __str__(self):
        status = '✓' if self.is_active else '✗'
        return f"{status} {self.name} — {self.date}"


# ──────────────────────────────────────────────────────────────
# 10. Daily Work Log (Log Book)
# ──────────────────────────────────────────────────────────────
class DailyWorkLog(models.Model):
    """
    Daily work status log entered by staff members.
    Aggregated for department-wise reports in MD, HR, and Dept Head views.
    """
    profile = models.ForeignKey(
        EmployeeProfile,
        on_delete=models.PROTECT,
        related_name='work_logs',
    )
    date = models.DateField(default=timezone.now)
    status_text = models.TextField(help_text="Detailed status of daily tasks and accomplishments.")
    hours_logged = models.DecimalField(max_digits=4, decimal_places=1, default=Decimal('8.0'))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'core_daily_work_log'
        ordering = ['-date', '-created_at']
        unique_together = ['profile', 'date']
        indexes = [
            models.Index(fields=['date', 'profile']),
        ]

    def __str__(self):
        return f"{self.profile.employee_id} | {self.date} | Log"


# ──────────────────────────────────────────────────────────────
# 11. Reimbursement Request
# ──────────────────────────────────────────────────────────────
class ReimbursementRequest(models.Model):
    """
    Staff reimbursement tracking. Includes bill upload.
    Workflow: Staff submits (PENDING) -> HR verifies (HR_VERIFIED) -> MD approves (APPROVED) or REJECTED.
    """

    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending HR Verification'
        HR_VERIFIED = 'HR_VERIFIED', 'HR Verified'
        APPROVED = 'APPROVED', 'Approved'
        REJECTED = 'REJECTED', 'Rejected'

    profile = models.ForeignKey(
        EmployeeProfile,
        on_delete=models.PROTECT,
        related_name='reimbursement_requests',
    )
    title = models.CharField(max_length=200, help_text='Expense title / description')
    description = models.TextField(blank=True)
    amount = models.DecimalField(
        max_digits=10, decimal_places=2,
        validators=[MinValueValidator(Decimal('0.01'))],
    )
    bill_file = models.FileField(upload_to='reimbursements/%Y/%m/', blank=True, null=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    rejection_reason = models.TextField(blank=True)
    
    hr_verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='verified_reimbursements',
    )
    hr_verified_at = models.DateTimeField(null=True, blank=True)

    md_approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='approved_reimbursements',
    )
    md_approved_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'core_reimbursement_request'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status', '-created_at']),
            models.Index(fields=['profile', 'status']),
        ]

    def __str__(self):
        return f"{self.profile.employee_id} | ₹{self.amount} | {self.status}"


# ──────────────────────────────────────────────────────────────
# 12. Staff Task Assignment
# ──────────────────────────────────────────────────────────────
class StaffTask(models.Model):
    """
    Task assigned by MD, GM, HR, or Department Head to staff.
    Staff can update status (PENDING, IN_PROGRESS, COMPLETED).
    """
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        IN_PROGRESS = 'IN_PROGRESS', 'In Progress'
        COMPLETED = 'COMPLETED', 'Completed'

    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='assigned_tasks',
    )
    assigned_to = models.ForeignKey(
        EmployeeProfile,
        on_delete=models.CASCADE,
        related_name='tasks',
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    due_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'core_staff_task'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} - {self.assigned_to.user.get_full_name()}"

