"""
PayrollService: pure-Python computation logic.

AEC Group Payroll Rules (STRICT):
- DAILY_RATE   = basic_salary / 30  (FIXED divisor — never use month length)
- HOURLY_RATE  = daily_rate / 8     (8-hour work day assumed)
- BASIC_EARNED = daily_rate * days_present
- OT_AMOUNT    = (hourly_rate * 2) * ot_hours  (double-time rate)
- PF           = 12% of basic_earned (NOT gross, NOT full basic)
- ESI          = 0.75% of gross if gross < 21,000
- Professional Tax (Kerala, monthly): 0 if gross<=12000 else 190/mo
  (half-yearly slabs still supported for backward compatibility)

KERALA_PT_SLABS — half-yearly amount (deducted Feb & Aug).
Reference: Kerala Municipal Act.
"""
from decimal import Decimal, ROUND_HALF_UP
from datetime import date
from calendar import monthrange

from core.models import (
    Attendance,
    EmployeeProfile,
    Incentive,
    Payroll,
)


# Half-yearly Professional Tax slabs (deducted in Aug for Apr-Sep, Feb for Oct-Mar)
KERALA_PT_SLABS = [
    (Decimal('11999'), Decimal('0')),
    (Decimal('17999'), Decimal('120')),
    (Decimal('29999'), Decimal('180')),
    (Decimal('44999'), Decimal('300')),
    (Decimal('59999'), Decimal('450')),
    (Decimal('74999'), Decimal('600')),
    (Decimal('99999'), Decimal('750')),
    (Decimal('124999'), Decimal('1000')),
    (Decimal('999999999'), Decimal('1250')),
]

ESI_THRESHOLD         = Decimal('21000')       # Gross < 21k = ESI eligible
ESI_RATE_EMPLOYEE     = Decimal('0.0075')      # 0.75% employee share
PF_RATE               = Decimal('0.12')        # 12% of earned basic
OT_MULTIPLIER         = Decimal('1')           # Normal hourly rate for OT
HOURS_PER_DAY        = Decimal('8')           # standard shift
# Monthly PT: if gross > 12,000 → ₹190/month (Kerala current slab)
PT_MONTHLY_THRESHOLD  = Decimal('12000')
PT_MONTHLY_AMOUNT     = Decimal('190')


def _q(value: Decimal) -> Decimal:
    """Round to 2 dp."""
    return value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def kerala_pt_for_basic(monthly_basic: Decimal, month_index: int) -> Decimal:
    """
    Returns Professional Tax for the *given month*. PT is paid twice a year
    (Aug for Apr-Sep, Feb for Oct-Mar) -> charge full half-yearly slab in
    those months, 0 otherwise.
    """
    if month_index not in PT_HALF_YEARLY_MONTHS:
        return Decimal('0.00')

    half_year_income = monthly_basic * Decimal('6')
    for ceiling, tax in KERALA_PT_SLABS:
        if half_year_income <= ceiling:
            return _q(tax)
    return _q(KERALA_PT_SLABS[-1][1])


def working_days_in_month(year: int, month: int, dept=None) -> int:
    """
    Returns count of working days for a given month according to the
    department's work_days config. Department is optional — falls back
    to Mon-Sat (excluding Sun) if not provided. Active Holidays for
    the department further reduce the count.
    """
    _, total = monthrange(year, month)
    if dept is not None:
        work_days = dept.get_work_days_list()
    else:
        work_days = [0, 1, 2, 3, 4, 5]  # Mon-Sat
    days = 0
    for day in range(1, total + 1):
        if date(year, month, day).weekday() in work_days:
            days += 1

    # Subtract holidays (active, applicable to dept or all)
    try:
        from django.db.models import Q as _Q
        from core.models import Holiday
        hol_qs = Holiday.objects.filter(
            is_active=True,
            date__year=year, date__month=month,
        )
        if dept is not None:
            hol_qs = hol_qs.filter(
                _Q(departments=dept) | _Q(departments__isnull=True)
            ).distinct()
        days -= hol_qs.count()
    except Exception:
        pass
    return max(0, days)


class PayrollService:
    """Pure computation — no DB writes here. Use generate_for_profile()
    helper to persist."""

    def __init__(self, profile: EmployeeProfile, year: int, month: int):
        self.profile = profile
        self.year = year
        self.month = month
        self.month_start = date(year, month, 1)
        self.basic = Decimal(profile.basic_salary)
        self.daily  = _q(self.basic / Decimal('30'))        # FIXED /30
        self.hourly = _q(self.daily / HOURS_PER_DAY)        # /8

    # ---------- Attendance / OT pulls ----------
    def get_days_present(self) -> int:
        return Attendance.objects.filter(
            profile=self.profile,
            date__year=self.year,
            date__month=self.month,
            in_time__isnull=False,
            is_valid=True,
        ).count()

    def get_ot_hours(self) -> Decimal:
        """Hours beyond 8 per shift, summed for the month."""
        records = Attendance.objects.filter(
            profile=self.profile,
            date__year=self.year,
            date__month=self.month,
            in_time__isnull=False,
            out_time__isnull=False,
            is_valid=True,
        )
        total = Decimal('0')
        for r in records:
            worked = Decimal(str(r.hours_worked))
            if worked > Decimal('8'):
                total += worked - Decimal('8')
        return _q(total)

    def get_incentive_total(self) -> Decimal:
        agg = Incentive.objects.filter(
            profile=self.profile,
            month__year=self.year,
            month__month=self.month,
        )
        return _q(sum((i.amount for i in agg), Decimal('0')))

    def get_discipline_deduction_days(self) -> Decimal:
        """Sum of active DisciplineRecord.deduction_days for this profile/month."""
        try:
            from assets.models import DisciplineRecord
            agg = DisciplineRecord.objects.filter(
                profile=self.profile,
                is_active=True,
                occurred_on__year=self.year,
                occurred_on__month=self.month,
            )
            total = sum((r.deduction_days for r in agg), Decimal('0'))
            return _q(total)
        except Exception:
            return Decimal('0')

    # ---------- Calculations ----------
    def compute(self) -> dict:
        working_days = working_days_in_month(self.year, self.month, self.profile.department)
        days_present = self.get_days_present()
        days_absent  = max(0, working_days - days_present)
        ot_hours     = self.get_ot_hours()
        incentive_total = self.get_incentive_total()

        # Leave policy
        from core.models import EmployeeProfile, LeaveRequest
        allowed_leaves = Decimal('1.0') if self.profile.probation_status == EmployeeProfile.ProbationStatus.PROBATION else Decimal('2.0')
        
        # Calculate half days taken
        approved_leaves = LeaveRequest.objects.filter(
            profile=self.profile,
            start_date__year=self.year,
            start_date__month=self.month,
            status=LeaveRequest.Status.APPROVED
        )
        half_leaves_taken = sum(1 for leave in approved_leaves if leave.leave_type == LeaveRequest.LeaveType.HALF_DAY)
        
        total_absent_value = Decimal(days_absent) + (Decimal(half_leaves_taken) * Decimal('0.5'))
        excess_leaves = max(Decimal('0.0'), total_absent_value - allowed_leaves)
        
        leave_deduction = _q(excess_leaves * self.daily)
        
        # Late Penalty (3rd occurrence onwards = 0.5 deduction)
        late_count = Attendance.objects.filter(
            profile=self.profile,
            date__year=self.year,
            date__month=self.month,
            is_late=True
        ).count()
        penalty_instances = max(0, late_count - 2)
        late_penalty_amount = _q(Decimal(penalty_instances) * (self.daily / Decimal('2')))
        
        # Other manual discipline deductions
        discipline_days = self.get_discipline_deduction_days()
        discipline_amount = _q(discipline_days * self.daily)
        
        total_leave_and_discipline_deductions = leave_deduction + late_penalty_amount + discipline_amount
        
        # Breakdown note
        breakdown = []
        if excess_leaves > 0:
            breakdown.append(f"{excess_leaves} Excess Leave (₹{leave_deduction})")
        if penalty_instances > 0:
            breakdown.append(f"{penalty_instances} Late Penalty (₹{late_penalty_amount})")
        if discipline_days > 0:
            breakdown.append(f"{discipline_days} Discipline (₹{discipline_amount})")
            
        deduction_notes = " + ".join(breakdown)
        if deduction_notes:
            deduction_notes += f" = Total ₹{total_leave_and_discipline_deductions}"

        # ── EARNINGS ────────────────────────────────────────────────────────
        ot_amount = _q(self.hourly * OT_MULTIPLIER * ot_hours)
        gross = _q(self.basic + ot_amount + incentive_total)

        # ── DEDUCTIONS ──────────────────────────────────────────────────────
        earned_basic = _q(self.basic - total_leave_and_discipline_deductions)
        if earned_basic < Decimal('0'):
            earned_basic = Decimal('0.00')

        # Rule 5a: PF = 12% of EARNED BASIC (not full basic, not gross)
        pf_ded = _q(earned_basic * PF_RATE)

        # Rule 5b: ESI = 0.75% of gross if gross < ₹21,000
        esi_ded = _q(gross * ESI_RATE_EMPLOYEE) if gross < ESI_THRESHOLD else Decimal('0.00')

        # Rule 5c: Professional Tax (Kerala) — monthly slab
        # If gross > ₹12,000 → ₹190/month; otherwise ₹0
        pt_ded = PT_MONTHLY_AMOUNT if gross > PT_MONTHLY_THRESHOLD else Decimal('0.00')

        total_ded = _q(total_leave_and_discipline_deductions + pt_ded + esi_ded + pf_ded)
        net       = _q(gross - total_ded)

        return {
            'profile_id':       self.profile.id,
            'employee_id':      self.profile.employee_id,
            'employee_name':    self.profile.user.get_full_name(),
            'department':       self.profile.department.name,
            'month':            self.month_start,
            'basic_salary':     _q(self.basic),
            'daily_rate':       self.daily,
            'hourly_rate':      self.hourly,
            'working_days':     working_days,
            'days_present':     days_present,
            'days_absent':      days_absent,
            'earned_basic':     earned_basic,
            'ot_hours':         ot_hours,
            'ot_amount':        ot_amount,
            'incentive_total':  incentive_total,
            'discipline_days':  discipline_days,
            'discipline_amount':total_leave_and_discipline_deductions,
            'deduction_notes':  deduction_notes,
            'gross_salary':     gross,
            'pt_deduction':     pt_ded,
            'esi_deduction':    esi_ded,
            'pf_deduction':     pf_ded,
            'total_deductions': total_ded,
            'net_salary':       net,
        }


def generate_for_profile(profile: EmployeeProfile, year: int, month: int, ot_override=None) -> Payroll:
    """Compute + persist (idempotent — updates existing draft)."""
    svc = PayrollService(profile, year, month)
    data = svc.compute()
    
    if ot_override is not None:
        data['ot_hours'] = Decimal(str(ot_override))
        data['ot_amount'] = _q(svc.hourly * Decimal('2') * data['ot_hours'])
        # Recompute gross and net
        gross = _q(data['basic_salary'] + data['ot_amount'] + data['incentive_total'])
        if gross < Decimal('0'):
            gross = Decimal('0.00')
        data['gross_salary'] = gross
        esi_ded = _q(gross * Decimal('0.0075')) if gross < Decimal('21000') else Decimal('0.00')
        pt_ded = Decimal('190') if gross > Decimal('12000') else Decimal('0.00')
        total_ded = _q(data['discipline_amount'] + pt_ded + esi_ded + data['pf_deduction'])
        data['esi_deduction'] = esi_ded
        data['pt_deduction'] = pt_ded
        data['total_deductions'] = total_ded
        data['net_salary'] = _q(gross - total_ded)

    obj, _created = Payroll.objects.get_or_create(
        profile=profile,
        month=data['month'],
        defaults={'status': Payroll.Status.DRAFT},
    )
    if obj.is_locked:
        return obj  # Don't touch finalized payrolls

    obj.basic_salary = data['basic_salary']
    obj.daily_rate = data['daily_rate']
    obj.working_days = data['working_days']
    obj.days_present = data['days_present']
    obj.days_absent = data['days_absent']
    obj.late_deduction_days = data['discipline_days']
    obj.ot_hours = data['ot_hours']
    obj.ot_amount = data['ot_amount']
    obj.incentive_total = data['incentive_total']
    obj.pt_deduction = data['pt_deduction']
    obj.esi_deduction = data['esi_deduction']
    obj.pf_deduction = data['pf_deduction']
    obj.other_deductions = data['discipline_amount']
    obj.deduction_notes = data['deduction_notes']
    obj.gross_salary = data['gross_salary']
    obj.total_deductions = data['total_deductions']
    obj.net_salary = data['net_salary']
    if obj.status == Payroll.Status.DRAFT:
        obj.status = Payroll.Status.HEAD_REVIEW
    obj.save()
    return obj


def generate_for_month(year: int, month: int) -> list:
    """Bulk-generate for all active employees. Returns list of Payroll."""
    out = []
    for profile in EmployeeProfile.objects.filter(is_active=True, probation_status__in=[EmployeeProfile.ProbationStatus.PROBATION, EmployeeProfile.ProbationStatus.PERMANENT]).select_related('user', 'department'):
        out.append(generate_for_profile(profile, year, month))
    return out


def scheduled_monthly_generation():
    """Scheduled job entrypoint (django-q2). Runs on the 28th of each month
    and generates payroll for the current month."""
    today = date.today()
    generate_for_month(today.year, today.month)
