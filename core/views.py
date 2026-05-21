from django.shortcuts import render, redirect
from django.contrib.auth import login
from core.models import User, Department, EmployeeProfile

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
                username=username,
                password=password,
                email=email,
                first_name=first_name,
                role=User.Role.MD,
                is_superuser=True,
                is_staff=True
            )
            
            # Create HQ Department if it doesn't exist
            dept, _ = Department.objects.get_or_create(
                name='AEC Enclave OPC Pvt Ltd', 
                defaults={'code': 'ENCLAVE', 'is_active': True}
            )
            
            # Create Employee Profile
            EmployeeProfile.objects.create(
                user=user,
                department=dept,
                probation_status=EmployeeProfile.ProbationStatus.PERMANENT
            )
            
            login(request, user)
            return redirect('dashboard')
            
    return render(request, 'registration/setup.html')

def signup(request):
    return redirect('login')

from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db.models import F
from decimal import Decimal
from core.models import ReimbursementRequest

@login_required
def reimbursements_view(request):
    ctx = {}
    u = request.user
    today = timezone.now().date()

    # Fetch current user profile
    my_profile = EmployeeProfile.objects.filter(
        user__email=u.email
    ).select_related('reporting_manager__user', 'department').order_by(
        F('date_of_joining').desc(nulls_last=True),
        F('designation').desc(nulls_last=True),
        '-id'
    ).first()

    if not my_profile and not u.is_superuser:
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

    ctx['my_profile'] = my_profile

    # Handle POST actions
    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'create_reimbursement' and my_profile:
            title = request.POST.get('title', '').strip()
            description = request.POST.get('description', '').strip()
            amount_str = request.POST.get('amount', '0')
            bill_file = request.FILES.get('bill_file')

            try:
                amount = Decimal(amount_str)
                if title and amount > 0:
                    ReimbursementRequest.objects.create(
                        profile=my_profile,
                        title=title,
                        description=description,
                        amount=amount,
                        bill_file=bill_file,
                        status=ReimbursementRequest.Status.PENDING
                    )
                    messages.success(request, "Reimbursement request submitted successfully.")
                else:
                    messages.error(request, "Please enter a valid title and amount.")
            except Exception as e:
                messages.error(request, f"Error submitting request: {str(e)}")
            return redirect('reimbursements')

        elif action == 'verify_reimbursement' and u.role == 'HR':
            req_id = request.POST.get('req_id')
            try:
                req = ReimbursementRequest.objects.get(id=req_id, status=ReimbursementRequest.Status.PENDING)
                req.status = ReimbursementRequest.Status.HR_VERIFIED
                req.hr_verified_by = u
                req.hr_verified_at = timezone.now()
                req.save()
                messages.success(request, "Reimbursement request verified successfully. Forwarded to MD.")
            except ReimbursementRequest.DoesNotExist:
                messages.error(request, "Request not found or already processed.")
            return redirect('reimbursements')

        elif action == 'approve_reimbursement' and u.role == 'MD':
            req_id = request.POST.get('req_id')
            try:
                req = ReimbursementRequest.objects.get(id=req_id, status=ReimbursementRequest.Status.HR_VERIFIED)
                req.status = ReimbursementRequest.Status.APPROVED
                req.md_approved_by = u
                req.md_approved_at = timezone.now()
                req.save()
                messages.success(request, "Reimbursement request approved successfully.")
            except ReimbursementRequest.DoesNotExist:
                messages.error(request, "Request not found or not in HR Verified status.")
            return redirect('reimbursements')

        elif action == 'reject_reimbursement' and u.role in ['HR', 'MD']:
            req_id = request.POST.get('req_id')
            reason = request.POST.get('rejection_reason', '').strip()
            try:
                req = ReimbursementRequest.objects.get(id=req_id)
                req.status = ReimbursementRequest.Status.REJECTED
                req.rejection_reason = reason
                if u.role == 'HR':
                    req.hr_verified_by = u
                    req.hr_verified_at = timezone.now()
                else:
                    req.md_approved_by = u
                    req.md_approved_at = timezone.now()
                req.save()
                messages.success(request, "Reimbursement request rejected.")
            except ReimbursementRequest.DoesNotExist:
                messages.error(request, "Request not found.")
            return redirect('reimbursements')

    # Staff view: My Requests
    if my_profile:
        ctx['my_requests'] = ReimbursementRequest.objects.filter(profile=my_profile).order_by('-created_at')
    else:
        ctx['my_requests'] = []

    # Department-wise lists for HR and MD
    departments = Department.objects.filter(is_active=True).order_by('name')
    dept_reimbursements = []

    for dept in departments:
        dept_reqs = ReimbursementRequest.objects.filter(profile__department=dept).select_related('profile__user')
        
        pending = dept_reqs.filter(status=ReimbursementRequest.Status.PENDING).order_by('created_at')
        verified = dept_reqs.filter(status=ReimbursementRequest.Status.HR_VERIFIED).order_by('created_at')
        
        if u.role == 'HR':
            history = dept_reqs.filter(status__in=[
                ReimbursementRequest.Status.HR_VERIFIED,
                ReimbursementRequest.Status.APPROVED,
                ReimbursementRequest.Status.REJECTED
            ]).order_by('-updated_at')
        elif u.role == 'MD':
            history = dept_reqs.filter(status__in=[
                ReimbursementRequest.Status.APPROVED,
                ReimbursementRequest.Status.REJECTED
            ]).order_by('-updated_at')
        else:
            history = []

        dept_reimbursements.append({
            'department': dept,
            'pending': pending,
            'verified': verified,
            'history': history,
            'has_items': pending.exists() or verified.exists() or (history.exists() if history else False)
        })

    ctx['dept_reimbursements'] = dept_reimbursements

    if u.role == 'MD':
        from django.db.models import Sum
        monthly_report = []
        total_monthly_spent = Decimal('0')
        for dept in departments:
            spent = ReimbursementRequest.objects.filter(
                profile__department=dept,
                status=ReimbursementRequest.Status.APPROVED,
                updated_at__year=today.year,
                updated_at__month=today.month
            ).aggregate(total=Sum('amount'))['total'] or Decimal('0')
            monthly_report.append({
                'department': dept,
                'spent': spent
            })
            total_monthly_spent += spent
        ctx['monthly_report'] = monthly_report
        ctx['total_monthly_spent'] = total_monthly_spent
        ctx['report_month_name'] = today.strftime('%B %Y')

    return render(request, 'reimbursements.html', ctx)


from core.models import StaffTask
from datetime import datetime
from twofa.emails import send_html_mail

@login_required
def tasks_view(request):
    ctx = {}
    u = request.user
    
    # Get profile
    my_profile = EmployeeProfile.objects.filter(user=u).first()
    if not my_profile and not u.is_superuser:
        dept, _ = Department.objects.get_or_create(name="Management" if u.role in ['MD', 'GM', 'HR'] else "General")
        my_profile = EmployeeProfile.objects.create(
            user=u,
            department=dept,
            designation=u.get_role_display(),
            basic_salary=Decimal('50000'),
            is_active=True,
            is_locked=True,
            probation_status='PERMANENT',
        )
    ctx['my_profile'] = my_profile

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'assign_task' and u.role in ['MD', 'GM', 'HR', 'DEPT_HEAD']:
            assigned_to_id = request.POST.get('assigned_to')
            title = request.POST.get('title', '').strip()
            description = request.POST.get('description', '').strip()
            due_date_str = request.POST.get('due_date')

            if title and assigned_to_id:
                try:
                    target_profile = EmployeeProfile.objects.get(id=assigned_to_id)
                    due_date = datetime.strptime(due_date_str, '%Y-%m-%d').date() if due_date_str else None
                    task = StaffTask.objects.create(
                        title=title,
                        description=description,
                        assigned_by=u,
                        assigned_to=target_profile,
                        due_date=due_date,
                        status=StaffTask.Status.PENDING
                    )
                    
                    # Notify staff via email / internal mail
                    if target_profile.user.email:
                        send_html_mail(
                            subject=f"[AEC HR] New Task Assigned: {title}",
                            template_name='email/leave_decision.html',  # generic template fallback
                            context={'message': f"You have been assigned a new task '{title}' by {u.get_full_name()}."},
                            to=[target_profile.user.email]
                        )
                    from communications.models import InternalMail
                    InternalMail.objects.create(
                        sender=u,
                        recipient=target_profile.user,
                        subject=f"📋 New Task: {title}",
                        body=f"Description: {description}\nDue Date: {due_date or 'No specific due date'}\nAssigned by: {u.get_full_name()}",
                        mail_type='GENERAL'
                    )
                    from notifications.models import Notification
                    Notification.objects.create(
                        title=f"📋 New Task Assigned: {title}",
                        message=f"Description: {description}\nDue Date: {due_date or 'No specific due date'}\nAssigned by: {u.get_full_name()}",
                        created_by=u,
                        notification_type='GENERAL',
                        target_profile=target_profile
                    )

                    messages.success(request, f"Task '{title}' assigned to {target_profile.user.get_full_name()}.")
                except Exception as e:
                    messages.error(request, f"Error assigning task: {str(e)}")
            else:
                messages.error(request, "Please enter title and select an employee.")
            return redirect('tasks')

        elif action == 'update_status':
            task_id = request.POST.get('task_id')
            new_status = request.POST.get('status')
            try:
                task = StaffTask.objects.get(id=task_id)
                if task.assigned_to == my_profile or u.role in ['MD', 'GM', 'HR', 'DEPT_HEAD']:
                    task.status = new_status
                    task.save()
                    messages.success(request, f"Task status updated to {task.get_status_display()}.")
                else:
                    messages.error(request, "Unauthorized to update this task.")
            except StaffTask.DoesNotExist:
                messages.error(request, "Task not found.")
            return redirect('tasks')

    # Query context
    if my_profile:
        ctx['my_tasks'] = StaffTask.objects.filter(assigned_to=my_profile).order_by('-created_at')
    else:
        ctx['my_tasks'] = []

    ctx['assigned_by_me'] = StaffTask.objects.filter(assigned_by=u).order_by('-created_at')
    
    # Manager context
    ctx['is_manager'] = u.role in ['MD', 'GM', 'HR', 'DEPT_HEAD']
    if ctx['is_manager']:
        all_staff = EmployeeProfile.objects.filter(is_active=True, probation_status__in=[EmployeeProfile.ProbationStatus.PROBATION, EmployeeProfile.ProbationStatus.PERMANENT]).select_related('user', 'department').order_by('department__name', 'user__first_name')
        if u.role == 'DEPT_HEAD':
            all_staff = all_staff.filter(department__head=u)
        ctx['all_staff'] = all_staff

        dept_reports = []
        departments = Department.objects.filter(is_active=True).order_by('name')
        if u.role == 'DEPT_HEAD':
            departments = departments.filter(head=u)

        for dept in departments:
            tasks = StaffTask.objects.filter(assigned_to__department=dept).select_related('assigned_to__user', 'assigned_by')
            dept_reports.append({
                'department': dept,
                'pending': tasks.filter(status='PENDING'),
                'in_progress': tasks.filter(status='IN_PROGRESS'),
                'completed': tasks.filter(status='COMPLETED'),
                'all_tasks': tasks.order_by('-created_at')
            })
        ctx['dept_reports'] = dept_reports

    return render(request, 'tasks.html', ctx)


