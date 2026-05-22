import json
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.http import JsonResponse
from .models import InviteToken
from .forms import HRInviteForm, CandidateOnboardingForm
from .utils import send_onboarding_email
from functools import wraps
from django.core.exceptions import PermissionDenied

from core.models import User

def is_hr_or_md(user):
    return user.is_authenticated and user.role in [User.Role.HR, User.Role.MD]

def hr_only(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        if request.user.role not in ('HR', 'MD'):
            raise PermissionDenied
        return view_func(request, *args, **kwargs)
    return _wrapped_view

@hr_only
def invite_candidate(request):
    if request.method == 'POST':
        form = HRInviteForm(request.POST)
        if form.is_valid():
            candidate = form.save()
            success, err_msg = send_onboarding_email(candidate, request)
            if success:
                messages.success(request, f"Invitation successfully sent to {candidate.email}")
            else:
                messages.error(request, f"Failed to dispatch email: {err_msg}")
            return redirect('onboarding:hr_verify_list')
    else:
        form = HRInviteForm()
    return render(request, 'onboarding/invite.html', {'form': form})

@hr_only
def hr_verify_list(request):
    from core.models import EmployeeProfile
    
    if request.method == 'POST':
        profile_id = request.POST.get('profile_id')
        action = request.POST.get('action')
        profile = get_object_or_404(EmployeeProfile, id=profile_id)
        
        if action == 'confirm':
            # Instead of activating, redirect to offer creation page
            return redirect('onboarding:create_offer', profile_id=profile.id)
        elif action == 'reject':
            reason_select = request.POST.get('reason_select')
            reason_text = request.POST.get('reason_text')
            reason = reason_text if reason_select == 'Other' else reason_select
            
            profile.onboarding_status = 'REJECTED'
            profile.rejection_reason = reason
            profile.save()
            messages.warning(request, f"Rejected candidate {profile.user.first_name}. Reason: {reason}")
            return redirect('onboarding:hr_verify_list')

    candidates = InviteToken.objects.filter(is_used=False)
    profiles = EmployeeProfile.objects.filter(onboarding_status='PENDING', is_active=False).select_related('user', 'department')
    
    return render(request, 'onboarding/hr_verify.html', {
        'candidates': candidates,
        'profiles': profiles,
    })

@hr_only
def hr_verify_detail(request, candidate_id):
    candidate = get_object_or_404(InviteToken, id=candidate_id)
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'approve':
            candidate.status = 'APPROVED'
            candidate.save()
            # Logic to convert candidate to employee profile can go here
            messages.success(request, f"Approved {candidate.full_name}")
        elif action == 'reject':
            candidate.status = 'REJECTED'
            candidate.save()
            messages.warning(request, f"Rejected {candidate.full_name}")
        return redirect('onboarding:hr_verify_list')
    return render(request, 'onboarding/hr_verify_detail.html', {'candidate': candidate})

@hr_only
def create_offer(request, profile_id):
    from core.models import EmployeeProfile
    from .forms import OfferLetterForm
    profile = get_object_or_404(EmployeeProfile, id=profile_id)
    
    if request.method == 'POST':
        form = OfferLetterForm(request.POST, instance=profile)
        if form.is_valid():
            form.save()
            request.session[f'offer_duties_{profile.id}'] = form.cleaned_data['duties']
            request.session[f'offer_probation_duration_{profile.id}'] = form.cleaned_data.get('probation_duration', '')
            request.session[f'offer_additional_notes_{profile.id}'] = form.cleaned_data.get('additional_notes', '')
            return redirect('onboarding:preview_offer', profile_id=profile.id)
    else:
        form = OfferLetterForm(instance=profile)
    
    return render(request, 'onboarding/create_offer.html', {'form': form, 'profile': profile})

@hr_only
def preview_offer(request, profile_id):
    from core.models import EmployeeProfile
    profile = get_object_or_404(EmployeeProfile, id=profile_id)
    duties = request.session.get(f'offer_duties_{profile.id}', '')
    probation_duration = request.session.get(f'offer_probation_duration_{profile.id}', '')
    additional_notes = request.session.get(f'offer_additional_notes_{profile.id}', '')

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'send':
            import re
            from datetime import timedelta
            
            if profile.probation_status == 'PROBATION' and probation_duration:
                months_match = re.search(r'(\d+)', probation_duration)
                if months_match and profile.date_of_joining:
                    months = int(months_match.group(1))
                    profile.probation_end_date = profile.date_of_joining + timedelta(days=months*30)
                elif profile.date_of_joining:
                    profile.probation_end_date = profile.date_of_joining + timedelta(days=30)
            elif profile.probation_status == 'PROBATION' and profile.date_of_joining:
                profile.probation_end_date = profile.date_of_joining + timedelta(days=30)

            profile.is_active = False
            profile.is_locked = True
            profile.onboarding_status = 'VERIFIED'
            profile.user.is_active = False
            profile.user.save()
            profile.save()

            # Create or update OfferLetter model record
            from communications.models import OfferLetter
            OfferLetter.objects.update_or_create(
                profile=profile,
                defaults={
                    'candidate_name': profile.user.get_full_name(),
                    'candidate_email': profile.user.email,
                    'department': profile.department,
                    'designation': profile.designation,
                    'probation_status': profile.probation_status,
                    'basic_salary': profile.basic_salary,
                    'date_of_joining': profile.date_of_joining,
                    'probation_duration': probation_duration,
                    'duties': duties,
                    'additional_notes': additional_notes,
                    'sent_by': request.user,
                    'is_sent': True,
                }
            )
            
            # Build the acceptance URL for the candidate
            from django.urls import reverse
            accept_path = reverse('onboarding:accept_offer', kwargs={'profile_id': profile.id})
            accept_url = request.build_absolute_uri(accept_path)

            # Send Email
            from twofa.emails import send_html_mail
            try:
                send_html_mail(
                    subject="AEC Group - Official Offer Letter",
                    template_name="onboarding/email_offer.html",
                    context={
                        'profile': profile,
                        'duties': duties,
                        'probation_duration': probation_duration,
                        'additional_notes': additional_notes,
                        'accept_url': accept_url,
                    },
                    to=[profile.user.email]
                )
                messages.success(request, f"Offer letter successfully sent to {profile.user.get_full_name()} and profile activated.")
            except Exception as e:
                messages.error(request, f"Profile activated, but failed to send email. Check SMTP settings.")
            
            return redirect('onboarding:hr_verify_list')
        elif action == 'edit':
            return redirect('onboarding:create_offer', profile_id=profile.id)
            
    return render(request, 'onboarding/preview_offer.html', {
        'profile': profile, 
        'duties': duties,
        'probation_duration': probation_duration,
        'additional_notes': additional_notes
    })

@hr_only
def mail_center(request):
    from core.models import EmployeeProfile
    sent_offers = EmployeeProfile.objects.filter(
        onboarding_status__in=['VERIFIED', 'ACCEPTED'],
        is_active=False,
    ).select_related('user', 'department')
    return render(request, 'onboarding/mail_center.html', {'sent_offers': sent_offers})

def accept_offer(request, profile_id):
    from core.models import EmployeeProfile
    profile = get_object_or_404(EmployeeProfile, id=profile_id)
    
    if profile.onboarding_status == 'ACCEPTED':
        return render(request, 'onboarding/success.html', {'message': 'You have already accepted this offer. HR is processing your profile.'})
        
    if request.method == 'POST':
        profile.onboarding_status = 'ACCEPTED'
        profile.save()
        
        from communications.models import InternalMail, OfferLetter
        from core.models import User
        from django.utils import timezone
        
        offer = OfferLetter.objects.filter(profile=profile).first()
        if offer:
            offer.is_accepted = True
            offer.accepted_at = timezone.now()
            offer.save()

        hr_users = User.objects.filter(role=User.Role.HR, is_active=True)
        for hr_user in hr_users:
            InternalMail.objects.create(
                sender_name=profile.user.get_full_name(),
                sender_email=profile.user.email,
                recipient=hr_user,
                subject=f"Offer Accepted - {profile.user.get_full_name()} ({profile.designation})",
                body=f"Candidate {profile.user.get_full_name()} has formally accepted the offer for {profile.designation}. Please verify and activate their profile.",
                mail_type='OFFER_ACCEPTANCE',
                related_offer=offer,
            )
            
        return render(request, 'onboarding/success.html', {'message': 'Offer accepted successfully! Your profile will be activated shortly.'})
        
    return render(request, 'onboarding/accept_offer.html', {'profile': profile})

@hr_only
def add_new_staff(request, profile_id):
    from core.models import EmployeeProfile, User
    import uuid
    import re
    profile = get_object_or_404(EmployeeProfile, id=profile_id)
    if request.method == 'POST':
        # Generate unique Employee ID
        dept_code = profile.department.code if profile.department and profile.department.code else "GEN"
        employee_id = f"AEC-{dept_code}-{uuid.uuid4().hex[:6].upper()}"
        
        # Username: the employee's name (lowercase, spaces replaced by underscore, unique)
        name_str = f"{profile.user.first_name}_{profile.user.last_name}"
        username = re.sub(r'[^a-zA-Z0-9_]', '', name_str.replace(' ', '_')).lower()
        
        original_username = username
        counter = 1
        while User.objects.filter(username=username).exists():
            username = f"{original_username}{counter}"
            counter += 1
            
        # Set employee credentials
        profile.employee_id = employee_id
        profile.is_active = True
        profile.onboarding_status = 'COMPLETED'
        profile.save()
        
        profile.user.username = username
        profile.user.set_password(employee_id)
        profile.user.is_active = True
        profile.user.save()
        
        # Save credentials in session so dashboard can display a nice copyable popup/banner
        request.session['new_staff_creds'] = {
            'name': profile.user.get_full_name(),  # Proper "First Last" with spaces
            'username': username,
            'password': employee_id,
            'dept': profile.department.name,
            'pos': profile.designation
        }
        
        messages.success(request, f"Successfully activated {profile.user.get_full_name()} as a new employee!")
        
    return redirect('onboarding:onboarding_dashboard')

@hr_only
def unlock_profile(request, profile_id):
    from core.models import EmployeeProfile
    profile = get_object_or_404(EmployeeProfile, id=profile_id)
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'unlock':
            profile.is_locked = False
            messages.success(request, f"Unlocked {profile.user.first_name}'s profile for document re-upload.")
        elif action == 'relock':
            profile.is_locked = True
            messages.success(request, f"Re-locked {profile.user.first_name}'s profile.")
        profile.save()
    return redirect('onboarding:hr_verify_list')

def candidate_onboarding_form(request, token):
    candidate = get_object_or_404(InviteToken, id=token)

    # Block resubmission - once used, no editing allowed
    if candidate.is_used:
        return render(request, 'onboarding/already_submitted.html', {'candidate': candidate})

    if request.method == 'POST':
        form = CandidateOnboardingForm(request.POST, request.FILES)
        if form.is_valid():
            data = form.cleaned_data
            from core.models import User, EmployeeProfile
            from django.core.files.storage import default_storage
            import uuid, re

            # ── Credential generation: name-based username (matches add_new_staff logic) ──
            first = data['first_name'].strip().upper()
            last  = data['last_name'].strip().upper()
            name_str = f"{first}_{last}"
            base_username = re.sub(r'[^a-zA-Z0-9_]', '', name_str.replace(' ', '_')).lower()
            username = base_username
            counter = 1
            while User.objects.filter(username=username).exists():
                username = f"{base_username}{counter}"
                counter += 1

            user = User.objects.create(
                username=username,
                email=candidate.email,
                first_name=first,
                last_name=last,
                phone=data['phone'],
                profile_picture=data['profile_pic'],
                date_of_birth=data.get('date_of_birth'),
                is_active=False
            )
            # Temporary password — will be replaced by Employee ID once HR activates
            user.set_password(str(uuid.uuid4()))
            user.save()

            docs_vault = {}
            all_doc_fields = [
                'id_proof', 'academic_doc',
                'certificate_10th', 'certificate_12th', 'certificate_degree',
                'other_certificates', 'exp_letter', 'salary_slips',
            ]
            for doc_field in all_doc_fields:
                file_obj = data.get(doc_field)
                if file_obj:
                    path = default_storage.save(f"vault/{user.username}/{file_obj.name}", file_obj)
                    docs_vault[doc_field] = {'url': default_storage.url(path), 'verified': False}

            # Bank details stored as split personal/salary JSON
            docs_vault['bank_details'] = {
                'personal': {
                    'bank_name':   data.get('personal_bank_name', ''),
                    'branch_name': data.get('personal_branch_name', ''),
                    'ifsc_code':   data.get('personal_ifsc', '').upper(),
                    'account':     data.get('personal_account', ''),
                },
                'salary': {
                    'bank_name':   data.get('salary_bank_name', ''),
                    'branch_name': data.get('salary_branch_name', ''),
                    'ifsc_code':   data.get('salary_ifsc', '').upper(),
                    'account':     data.get('salary_account', ''),
                },
            }

            docs_vault['emergency_contact'] = {
                'name':         data.get('emergency_contact_name', ''),
                'relationship': data.get('emergency_contact_rel', ''),
                'phone':        data.get('emergency_contact_phone', ''),
            }
            if data.get('pan_number'):
                docs_vault['pan'] = data.get('pan_number').upper()
            if data.get('gender'):
                docs_vault['gender'] = data.get('gender')

            profile = EmployeeProfile.objects.create(
                user=user,
                department=candidate.department,
                address=data.get('address', ''),
                personal_account=data.get('personal_account', ''),
                salary_account=data.get('salary_account', ''),
                aadhaar_masked='X' * 8 + data['aadhaar'][-4:] if len(data['aadhaar']) >= 4 else '',
                emergency_contact=data.get('emergency_contact_phone', '')[:15],
                docs_vault=docs_vault,
                is_locked=True,
                is_active=False
            )

            candidate.profile = profile
            candidate.is_used = True
            candidate.save()
            return redirect('onboarding:onboarding_success')
    else:
        form = CandidateOnboardingForm()
    return render(request, 'onboarding/candidate_form.html', {'form': form, 'candidate': candidate, 'invite': candidate})

def onboarding_success(request):
    return render(request, 'onboarding/success.html')

@hr_only
def onboarding_dashboard(request):
    from core.models import EmployeeProfile

    new_staff_creds = request.session.pop('new_staff_creds', None)

    verified_candidates = EmployeeProfile.objects.filter(onboarding_status__in=['VERIFIED', 'ACCEPTED']).select_related('user', 'department')
    rejected_candidates = EmployeeProfile.objects.filter(onboarding_status='REJECTED').select_related('user', 'department')

    # Candidates who submitted the onboarding form and are waiting for HR review
    verification_requests = EmployeeProfile.objects.filter(
        onboarding_status='PENDING',
        is_active=False,
    ).select_related('user', 'department')

    pending_count = verification_requests.count()

    return render(request, 'onboarding/dashboard.html', {
        'verified_candidates': verified_candidates,
        'rejected_candidates': rejected_candidates,
        'verification_requests': verification_requests,
        'pending_count': pending_count,
        'new_staff_creds': new_staff_creds,
    })

@hr_only
def quick_terminate(request, profile_id):
    from core.models import EmployeeProfile
    profile = get_object_or_404(EmployeeProfile, id=profile_id)
    if request.method == 'POST':
        profile.probation_status = 'TERMINATED'
        profile.is_active = False
        profile.user.is_active = False
        profile.user.save()
        profile.save()
        messages.success(request, f"{profile.user.get_full_name()} has been marked as Terminated.")
    return redirect('onboarding:onboarding_dashboard')

@hr_only
def confirm_permanency(request, profile_id):
    from core.models import EmployeeProfile
    profile = get_object_or_404(EmployeeProfile, id=profile_id)
    if request.method == 'POST':
        profile.probation_status = 'PERMANENT'
        profile.save()
        messages.success(request, f"{profile.user.get_full_name()} is now a Permanent Employee!")
    return redirect('onboarding:onboarding_dashboard')


@hr_only
def mail_center_duplicate(request):
    # Removing duplicate mail_center view
    pass





@login_required
def staff_directory(request):
    from core.models import Department, EmployeeProfile, User
    new_staff_creds = request.session.pop('new_staff_creds', None)
    # Include all active departments
    departments = Department.objects.filter(is_active=True).order_by('name')
    staff_by_department = []
    total_permanent = 0
    total_probation = 0
    total_terminated = 0

    for dept in departments:
        # Exclude MD from staff list
        profiles = EmployeeProfile.objects.filter(department=dept).exclude(user__role=User.Role.MD).select_related('user')
        probation   = list(profiles.filter(probation_status='PROBATION', is_active=True))
        permanent   = list(profiles.filter(probation_status='PERMANENT', is_active=True))
        terminated  = list(profiles.filter(probation_status='TERMINATED'))
        total = len(probation) + len(permanent) + len(terminated)

        # Always append department even if total == 0 to show all departments
        staff_by_department.append({
            'department':        dept,
            'probation':         probation,
            'permanent':         permanent,
            'terminated':        terminated,
            'total':             total,
            'probation_count':   len(probation),
            'permanent_count':   len(permanent),
            'terminated_count':  len(terminated),
        })
        total_permanent  += len(permanent)
        total_probation  += len(probation)
        total_terminated += len(terminated)

    return render(request, 'onboarding/staff_directory.html', {
        'staff_by_department': staff_by_department,
        'total_permanent':  total_permanent,
        'total_probation':  total_probation,
        'total_terminated': total_terminated,
        'active_employees': EmployeeProfile.objects.filter(is_active=True, probation_status__in=[EmployeeProfile.ProbationStatus.PROBATION, EmployeeProfile.ProbationStatus.PERMANENT]).exclude(user__role=User.Role.MD).select_related('user').order_by('user__first_name'),
        'new_staff_creds':  new_staff_creds,
    })


@hr_only
def add_staff_form(request):
    from core.models import Department, EmployeeProfile, User as _User
    import uuid as _uuid

    departments = Department.objects.filter(is_active=True).order_by('name')

    if request.method == 'POST':
        # --- User fields ---
        first_name = request.POST.get('first_name', '').strip().upper()
        last_name  = request.POST.get('last_name', '').strip().upper()
        email      = request.POST.get('email', '').strip()
        phone      = request.POST.get('phone', '').strip()
        dob        = request.POST.get('date_of_birth') or None
        gender     = request.POST.get('gender', '').strip()

        # --- Profile fields ---
        dept_id          = request.POST.get('department')
        designation      = request.POST.get('designation', '').strip()
        basic_salary     = request.POST.get('basic_salary', '0')
        date_of_joining  = request.POST.get('date_of_joining') or None
        probation_status = request.POST.get('probation_status', 'PROBATION')
        address          = request.POST.get('address', '').strip()
        aadhaar_masked   = request.POST.get('aadhaar_masked', '').strip()
        emergency_contact_name  = request.POST.get('emergency_contact_name', '').strip()
        emergency_contact_rel   = request.POST.get('emergency_contact_rel', '').strip()
        emergency_contact_phone = request.POST.get('emergency_contact_phone', '').strip()
        # Bank fields — split into personal and salary
        personal_bank_name = request.POST.get('personal_bank_name', '').strip()
        personal_branch_name = request.POST.get('personal_branch_name', '').strip()
        personal_ifsc      = request.POST.get('personal_ifsc', '').strip().upper()
        personal_account   = request.POST.get('personal_account', '').strip()
        salary_bank_name   = request.POST.get('salary_bank_name', '').strip()
        salary_branch_name = request.POST.get('salary_branch_name', '').strip()
        salary_ifsc        = request.POST.get('salary_ifsc', '').strip().upper()
        salary_account     = request.POST.get('salary_account', '').strip()

        if not (first_name and last_name and email and dept_id):
            messages.error(request, 'First name, last name, email and department are required.')
            return render(request, 'onboarding/add_staff_form.html', {
                'departments': departments, 'post': request.POST,
            })

        # Generate Employee ID (used as initial password)
        dept = Department.objects.get(pk=dept_id)
        employee_id = f"AEC-{dept.code}-{_uuid.uuid4().hex[:6].upper()}"

        # Username = name-based (e.g. athira_athira) — readable & memorable
        import re as _re
        name_str = f"{first_name}_{last_name}"
        base_uname = _re.sub(r'[^a-zA-Z0-9_]', '', name_str.replace(' ', '_')).lower()
        uname = base_uname
        counter = 1
        while _User.objects.filter(username=uname).exists():
            uname = f"{base_uname}{counter}"
            counter += 1

        user = _User.objects.create_user(
            username=uname, email=email,
            first_name=first_name, last_name=last_name,
            phone=phone, role='STAFF', is_active=True,
        )
        # Initial password = Employee ID
        user.set_password(employee_id)
        if dob:
            user.date_of_birth = dob
        photo = request.FILES.get('profile_picture')
        if photo:
            user.profile_picture = photo
        user.save()

        # docs_vault stores full emergency contact details + bank details + certificates
        vault = {}
        if emergency_contact_name:
            vault['emergency_contact'] = {
                'name':         emergency_contact_name,
                'relationship': emergency_contact_rel,
                'phone':        emergency_contact_phone,
            }

        vault['bank_details'] = {
            'personal': {
                'bank_name':    personal_bank_name,
                'branch_name':  personal_branch_name,
                'ifsc_code':    personal_ifsc,
                'account':      personal_account,
            },
            'salary': {
                'bank_name':    salary_bank_name,
                'branch_name':  salary_branch_name,
                'ifsc_code':    salary_ifsc,
                'account':      salary_account,
            },
        }

        # File-based certificates
        from django.core.files.storage import default_storage as _ds
        cert_fields = [
            'id_proof', 'academic_doc',
            'certificate_10th', 'certificate_12th', 'certificate_degree',
            'other_certificates', 'exp_letter', 'salary_slips',
        ]
        for cf in cert_fields:
            file_obj = request.FILES.get(cf)
            if file_obj:
                fpath = _ds.save(f"vault/{uname}/{file_obj.name}", file_obj)
                vault[cf] = {'url': _ds.url(fpath), 'verified': False}

        # No reporting_manager set at creation time — HR assigns from Staff Profile page
        reporting_manager = None

        profile = EmployeeProfile(
            user=user, department=dept,
            designation=designation,
            basic_salary=basic_salary or 0,
            date_of_joining=date_of_joining,
            probation_status=probation_status,
            address=address,
            aadhaar_masked=aadhaar_masked,
            emergency_contact=emergency_contact_phone[:15] if emergency_contact_phone else '',
            personal_account=personal_account,
            salary_account=salary_account,
            onboarding_status='COMPLETED',
            docs_vault=vault,
            is_active=True,
            reporting_manager=reporting_manager,
        )
        profile.employee_id = employee_id
        profile.save()

        # Store credentials in session for HR to see and copy
        # Display name uses proper spaces "First Last"
        display_name = f"{first_name} {last_name}"
        request.session['new_staff_creds'] = {
            'name':     display_name,
            'username': uname,        # Login ID = name-based username (e.g. athira_athira)
            'password': employee_id,  # Password = Employee ID
            'dept':     dept.name,
            'pos':      designation,
        }

        messages.success(request, f"{user.get_full_name()} added successfully (ID: {employee_id}).")
        return redirect('onboarding:staff_directory')

    return render(request, 'onboarding/add_staff_form.html', {
        'departments': departments,
    })


@login_required
@user_passes_test(is_hr_or_md)
def assign_manager(request, profile_id):
    """
    HR endpoint: assign or change a reporting manager for an existing employee.
    Enforces circular-reporting prevention by walking the full manager chain.
    """
    from core.models import EmployeeProfile

    profile = get_object_or_404(EmployeeProfile, pk=profile_id, is_active=True, probation_status__in=[EmployeeProfile.ProbationStatus.PROBATION, EmployeeProfile.ProbationStatus.PERMANENT])

    if request.method == 'POST':
        mgr_id = request.POST.get('reporting_manager_id') or None

        if not mgr_id:
            profile.reporting_manager = None
            profile.save(update_fields=['reporting_manager'])
            messages.success(request, f"Reporting manager removed for {profile.user.get_full_name()}.")
            return redirect('onboarding:staff_directory')

        try:
            new_mgr = EmployeeProfile.objects.get(pk=mgr_id, is_active=True, probation_status__in=[EmployeeProfile.ProbationStatus.PROBATION, EmployeeProfile.ProbationStatus.PERMANENT])
        except EmployeeProfile.DoesNotExist:
            messages.error(request, "Manager not found.")
            return redirect('onboarding:staff_directory')

        # Circular detection: walk new_mgr's own chain and ensure `profile` is not in it
        visited = set()
        cursor = new_mgr
        circular = False
        while cursor is not None:
            if cursor.pk == profile.pk:
                circular = True
                break
            if cursor.pk in visited:
                break
            visited.add(cursor.pk)
            cursor = cursor.reporting_manager

        if circular:
            messages.error(
                request,
                f"Circular reporting detected: {new_mgr.user.get_full_name()} already reports "
                f"(directly or indirectly) to {profile.user.get_full_name()}."
            )
            return redirect('onboarding:staff_directory')

        profile.reporting_manager = new_mgr
        profile.save(update_fields=['reporting_manager'])
        messages.success(
            request,
            f"{new_mgr.user.get_full_name()} assigned as Reporting Manager for {profile.user.get_full_name()}."
        )

    return redirect('onboarding:staff_directory')


@login_required
@user_passes_test(is_hr_or_md)
def delete_staff_profile(request, profile_id):
    """
    HR/MD only: permanently delete a staff profile and their user account.
    Requires a POST with confirm=yes to prevent accidental deletion.
    """
    from core.models import EmployeeProfile
    profile = get_object_or_404(EmployeeProfile, pk=profile_id)

    # Prevent deleting the currently logged-in user
    if profile.user == request.user:
        messages.error(request, "You cannot delete your own account.")
        return redirect('onboarding:staff_directory')

    if request.method == 'POST' and request.POST.get('confirm') == 'yes':
        full_name = profile.user.get_full_name()
        emp_id    = profile.employee_id

        # Delete related protected records
        profile.attendance_records.all().delete()
        profile.leave_requests.all().delete()
        profile.incentives.all().delete()
        profile.payroll_records.all().delete()
        profile.work_logs.all().delete()
        profile.reimbursement_requests.all().delete()
        profile.assets.all().delete()
        profile.nocs.all().delete()
        profile.discipline_records.all().delete()

        # Disassociate reporting manager link to avoid self-referential issues
        profile.team_members.all().update(reporting_manager=None)

        # Audit logs have a custom delete() that throws an error, so we nullify the profile field
        profile.audit_logs.all().update(profile=None)

        # Delete user (cascades to profile via OneToOne if set up that way)
        user = profile.user
        profile.delete()
        try:
            user.delete()
        except Exception:
            pass  # already cascaded

        messages.success(request, f"✅ {full_name} ({emp_id}) has been permanently removed from the system.")
        return redirect('onboarding:staff_directory')

    # Any other method → redirect without action
    messages.error(request, "Invalid delete request.")
    return redirect('onboarding:staff_directory')


@login_required
def staff_detail(request, profile_id=None):
    """Full profile detail page for any employee."""
    from core.models import EmployeeProfile, Attendance, LeaveRequest
    from django.utils import timezone
    from datetime import date

    if request.user.role == 'STAFF':
        # Fetch profile strictly by the logged-in user object — NEVER by email
        # (email-based lookup causes wrong profile if multiple accounts share an email)
        profile = EmployeeProfile.objects.filter(
            user=request.user
        ).select_related(
            'user', 'department', 'reporting_manager__user'
        ).order_by('-id').first()
        if not profile:
            raise Http404("No employee profile found for your account.")
    elif profile_id:
        # HR/MD can view any specific profile
        profile = get_object_or_404(
            EmployeeProfile.objects.select_related(
                'user', 'department', 'reporting_manager__user', 'reporting_manager__department'
            ),
            pk=profile_id,
        )
    else:
        # Fallback for HR/MD viewing their own profile (no profile_id given)
        # Also use exact user match — not email
        profile = EmployeeProfile.objects.filter(
            user=request.user
        ).select_related(
            'user', 'department', 'reporting_manager__user'
        ).order_by('-id').first()
        if not profile:
            raise Http404("No employee profile found for this account.")

    # Handle POST request for updating email and password
    if request.method == 'POST' and request.POST.get('action') == 'update_credentials':
        # Verify that the logged-in user is viewing their own profile page to change credentials
        is_own_profile = (profile.user.email == request.user.email)
        if not is_own_profile:
            messages.error(request, "You can only change your own credentials.")
            return redirect('onboarding:my_profile')

        new_email = request.POST.get('new_email', '').strip().lower()
        new_password = request.POST.get('new_password', '').strip()
        current_password = request.POST.get('current_password', '').strip()

        # 1. Basic validation
        if not new_email:
            messages.error(request, "Email address is required.")
            return redirect('onboarding:my_profile')

        # 2. Check current password
        if not request.user.check_password(current_password):
            messages.error(request, "Incorrect current password. Verification failed.")
            return redirect('onboarding:my_profile')

        # 3. Check if new email is already in use by another person
        from core.models import User
        if User.objects.filter(email=new_email).exclude(email=request.user.email).exists():
            messages.error(request, "This email address is already in use.")
            return redirect('onboarding:my_profile')

        # 4. Find all users sharing the old email
        old_email = request.user.email
        users_to_update = list(User.objects.filter(email=old_email))

        # Generate unique username base for the logged-in user
        base_username = new_email.split('@')[0]
        new_username = base_username
        c = 1
        while User.objects.filter(username=new_username).exclude(id=request.user.id).exists():
            new_username = f"{base_username}{c}"
            c += 1

        # 5. Update email (and username of currently logged-in user) and password
        for u in users_to_update:
            u.email = new_email
            if u.id == request.user.id:
                u.username = new_username
            if new_password:
                u.set_password(new_password)
            u.save()

        # 6. Keep session active
        if new_password:
            from django.contrib.auth import update_session_auth_hash
            update_session_auth_hash(request, request.user)

        messages.success(request, f"✅ Your email has been successfully updated to {new_email}. Your new sign-in ID is '{new_username}'.")
        return redirect('onboarding:my_profile')

    if request.method == 'POST' and request.POST.get('action') == 'update_personal_details':
        wedding_anniversary = request.POST.get('wedding_anniversary') or None
        spouse_name = request.POST.get('spouse_name', '').strip()
        blood_group = request.POST.get('blood_group', '').strip()
        hobbies = request.POST.get('hobbies', '').strip()
        dob = request.POST.get('date_of_birth') or None
        phone = request.POST.get('phone', '').strip()
        address = request.POST.get('address', '').strip()
        emergency_contact = request.POST.get('emergency_contact', '').strip()

        profile.wedding_anniversary = wedding_anniversary
        profile.spouse_name = spouse_name
        profile.blood_group = blood_group
        profile.hobbies = hobbies
        profile.address = address
        profile.emergency_contact = emergency_contact
        profile.save()

        profile.user.phone = phone
        if dob:
            profile.user.date_of_birth = dob
        profile.user.save()

        try:
            from core.wishes_service import ensure_daily_wishes_and_alerts
            ensure_daily_wishes_and_alerts()
        except Exception:
            pass

        messages.success(request, "✅ Personal details and automated wishes configuration successfully updated.")
        if request.resolver_match.url_name == 'my_profile':
            return redirect('onboarding:my_profile')
        return redirect('onboarding:staff_detail', profile_id=profile.id)

    if request.method == 'POST' and request.POST.get('action') == 'assign_manager':
        if request.user.role not in ('HR', 'MD'):
            messages.error(request, "Only HR can assign a reporting manager.")
            return redirect('onboarding:staff_detail', profile_id=profile.id)
        from core.models import EmployeeProfile as _EP
        mgr_id = request.POST.get('reporting_manager_id', '').strip()
        if mgr_id:
            try:
                new_mgr = _EP.objects.get(pk=mgr_id, is_active=True)
                if new_mgr.pk == profile.pk:
                    messages.error(request, "An employee cannot report to themselves.")
                else:
                    profile.reporting_manager = new_mgr
                    profile.save()
                    messages.success(request, f"Reporting manager set to {new_mgr.user.get_full_name()}.")
            except _EP.DoesNotExist:
                messages.error(request, "Selected manager not found.")
        else:
            profile.reporting_manager = None
            profile.save()
            messages.success(request, "Reporting manager removed.")
        return redirect('onboarding:staff_detail', profile_id=profile.id)

    today = date.today()

    # Last 5 attendance records
    recent_attendance = Attendance.objects.filter(
        profile=profile
    ).order_by('-date')[:5]

    # Current month leave summary
    leave_requests = LeaveRequest.objects.filter(
        profile=profile
    ).order_by('-created_at')[:10]

    # Team members (if this person is a manager)
    team_members = profile.team_members.filter(is_active=True).select_related('user', 'department')

    # Docs vault
    vault = profile.docs_vault or {}
    emergency = vault.get('emergency_contact', {})

    from core.models import EmployeeProfile as _EP2, User as _U2
    active_employees = _EP2.objects.filter(is_active=True, probation_status__in=[_EP2.ProbationStatus.PROBATION, _EP2.ProbationStatus.PERMANENT]).exclude(pk=profile.pk).select_related('user').order_by('user__first_name')

    return render(request, 'onboarding/staff_detail.html', {
        'profile': profile,
        'recent_attendance': recent_attendance,
        'leave_requests': leave_requests,
        'team_members': team_members,
        'emergency': emergency,
        'vault': vault,
        'today': today,
        'active_employees': active_employees,
    })