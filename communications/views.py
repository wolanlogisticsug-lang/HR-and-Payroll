from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.db.models import Q
from core.models import User
from .models import InternalMail, OfferLetter
from functools import wraps
from django.core.exceptions import PermissionDenied


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



# ─────────────────────────────────────────────
# INBOX  (received mails)
# ─────────────────────────────────────────────
@login_required
def inbox(request):
    mails = InternalMail.objects.filter(
        Q(recipient=request.user) | Q(recipient_email=request.user.email)
    ).order_by('-created_at')
    unread_count = mails.filter(is_read=False).count()
    return render(request, 'communications/inbox.html', {
        'mails': mails,
        'box_type': 'inbox',
        'unread_count': unread_count,
    })


# ─────────────────────────────────────────────
# SENT MAILS
# ─────────────────────────────────────────────
@login_required
def sent_mails(request):
    mails = InternalMail.objects.filter(sender=request.user).order_by('-created_at')
    return render(request, 'communications/inbox.html', {
        'mails': mails,
        'box_type': 'sent',
        'unread_count': 0,
    })


# ─────────────────────────────────────────────
# MAIL DETAIL
# ─────────────────────────────────────────────
@login_required
def mail_detail(request, mail_id):
    mail = get_object_or_404(InternalMail, id=mail_id)

    is_recipient = (
        mail.recipient == request.user or
        mail.recipient_email == request.user.email
    )
    is_sender = (mail.sender == request.user)

    if not is_recipient and not is_sender:
        messages.error(request, "Access denied.")
        return redirect('communications:inbox')

    if is_recipient and not mail.is_read:
        mail.is_read = True
        mail.save()

    return render(request, 'communications/mail_detail.html', {'mail': mail})


# ─────────────────────────────────────────────
# COMPOSE
# ─────────────────────────────────────────────
@login_required
def compose(request):
    if request.method == 'POST':
        recipient_email = request.POST.get('recipient_email')
        subject = request.POST.get('subject')
        body = request.POST.get('body')
        recipient_user = User.objects.filter(email=recipient_email).first()
        InternalMail.objects.create(
            sender=request.user,
            recipient=recipient_user,
            recipient_email=recipient_email,
            subject=subject,
            body=body,
            mail_type='GENERAL',
        )
        
        # Send actual external email in background
        def send_bg_mail():
            try:
                from django.core.mail import send_mail
                from django.conf import settings
                send_mail(
                    subject=subject,
                    message=body,
                    from_email=settings.DEFAULT_FROM_EMAIL,
                    recipient_list=[recipient_email],
                    fail_silently=False,
                )
            except Exception as e:
                print(f"Background email failed: {e}")

        import threading
        threading.Thread(target=send_bg_mail, daemon=True).start()

        messages.success(request, "Mail sent successfully.")
        return redirect('communications:sent_mails')

    prefill_email = request.GET.get('reply_to', '')
    return render(request, 'communications/compose.html', {'prefill_email': prefill_email})


# ─────────────────────────────────────────────
# CUSTOMISED MAILS HUB
# ─────────────────────────────────────────────
@login_required
@user_passes_test(is_hr_or_md)
def send_promotion(request):
    return render(request, 'communications/promotion.html')


# ─────────────────────────────────────────────
# STEP 1: GENERATE OFFER LETTER FORM
# ─────────────────────────────────────────────
@hr_only
def generate_offer_letter(request):
    from .forms import OfferLetterForm

    if request.method == 'POST':
        form = OfferLetterForm(request.POST)
        if form.is_valid():
            d = form.cleaned_data
            offer = OfferLetter.objects.create(
                candidate_name=d['candidate_name'],
                candidate_email=d['candidate_email'],
                department=d['department'],
                designation=d['designation'],
                probation_status=d['probation_status'],
                basic_salary=d['basic_salary'],
                date_of_joining=d.get('date_of_joining'),
                probation_duration=d.get('probation_duration', ''),
                duties=d.get('duties', ''),
                additional_notes=d.get('additional_notes', ''),
                sent_by=request.user,
            )
            return redirect('communications:offer_preview', offer_id=offer.id)
    else:
        form = OfferLetterForm()

    return render(request, 'communications/offer_letter_form.html', {'form': form})


# ─────────────────────────────────────────────
# STEP 2: PREVIEW + SEND OFFER
# ─────────────────────────────────────────────
@hr_only
def offer_preview(request, offer_id):
    offer = get_object_or_404(OfferLetter, id=offer_id)

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'edit':
            return redirect('communications:offer_edit', offer_id=offer.id)

        if action == 'send' and not offer.is_sent:
            # Build the candidate accept URL
            from django.urls import reverse
            accept_path = reverse('communications:offer_accept', kwargs={'token': offer.token})
            accept_url = request.build_absolute_uri(accept_path)

            # Send offer email to candidate
            try:
                from twofa.emails import send_html_mail
                send_html_mail(
                    subject=f"AEC Group – Official Offer Letter: {offer.designation}",
                    template_name='communications/email_offer_letter.html',
                    context={'offer': offer, 'accept_url': accept_url},
                    to=[offer.candidate_email],
                )
            except Exception as e:
                messages.warning(request, f"Offer saved but email failed: {e}")

            # Log it as a sent internal mail record
            InternalMail.objects.create(
                sender=request.user,
                recipient_email=offer.candidate_email,
                subject=f"Offer Letter sent to {offer.candidate_name}",
                body=(
                    f"Offer letter for {offer.designation} sent to "
                    f"{offer.candidate_name} ({offer.candidate_email}).\n"
                    f"Department: {offer.department}\n"
                    f"Salary: ₹{offer.basic_salary}"
                ),
                mail_type='OFFER',
                related_offer=offer,
            )

            offer.is_sent = True
            offer.save()
            messages.success(
                request,
                f"✅ Offer letter sent to {offer.candidate_name} ({offer.candidate_email})."
            )
            return redirect('communications:sent_mails')

    return render(request, 'communications/offer_preview.html', {'offer': offer})


# ─────────────────────────────────────────────
# EDIT OFFER (pre-send)
# ─────────────────────────────────────────────
@hr_only
def offer_edit(request, offer_id):
    from .forms import OfferLetterForm
    offer = get_object_or_404(OfferLetter, id=offer_id, is_sent=False)

    initial = {
        'candidate_name': offer.candidate_name,
        'candidate_email': offer.candidate_email,
        'department': offer.department,
        'designation': offer.designation,
        'probation_status': offer.probation_status,
        'basic_salary': offer.basic_salary,
        'date_of_joining': offer.date_of_joining,
        'probation_duration': offer.probation_duration,
        'duties': offer.duties,
        'additional_notes': offer.additional_notes,
    }

    if request.method == 'POST':
        form = OfferLetterForm(request.POST)
        if form.is_valid():
            d = form.cleaned_data
            offer.candidate_name = d['candidate_name']
            offer.candidate_email = d['candidate_email']
            offer.department = d['department']
            offer.designation = d['designation']
            offer.probation_status = d['probation_status']
            offer.basic_salary = d['basic_salary']
            offer.date_of_joining = d.get('date_of_joining')
            offer.probation_duration = d.get('probation_duration', '')
            offer.duties = d.get('duties', '')
            offer.additional_notes = d.get('additional_notes', '')
            offer.save()
            return redirect('communications:offer_preview', offer_id=offer.id)
    else:
        form = OfferLetterForm(initial=initial)

    return render(request, 'communications/offer_letter_form.html', {
        'form': form,
        'offer': offer,
        'editing': True,
    })


# ─────────────────────────────────────────────
# CANDIDATE: ACCEPT OFFER  (public, no login)
# ─────────────────────────────────────────────
def offer_accept(request, token):
    offer = get_object_or_404(OfferLetter, token=token)

    if not offer.is_sent:
        return render(request, 'communications/offer_already_handled.html', {
            'message': "This offer link is not yet active. Please wait for HR to send your offer.",
        })

    if offer.is_accepted:
        return render(request, 'communications/offer_already_handled.html', {
            'message': "You have already accepted this offer. HR is processing your application.",
        })

    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        last_name  = request.POST.get('last_name', '').strip()
        phone      = request.POST.get('phone', '').strip()
        photo      = request.FILES.get('photo')

        if not first_name:
            messages.error(request, "Please enter your first name.")
            return render(request, 'communications/offer_accept.html', {'offer': offer})

        from core.models import User, EmployeeProfile, Department
        from django.utils import timezone
        import uuid as _uuid

        # Create or find User
        email = offer.candidate_email
        user = User.objects.filter(email=email).first()
        if not user:
            base_uname = email.split('@')[0]
            uname = base_uname
            c = 1
            while User.objects.filter(username=uname).exists():
                uname = f"{base_uname}{c}"; c += 1

            user = User(
                username=uname,
                email=email,
                first_name=first_name,
                last_name=last_name,
                phone=phone,
                is_active=False,
                role='STAFF',
            )
            user.set_password(_uuid.uuid4().hex)
            if photo:
                user.profile_picture = photo
            user.save()
        else:
            # Update existing user details
            user.first_name = first_name
            user.last_name  = last_name
            user.phone      = phone
            if photo:
                user.profile_picture = photo
            user.save()

        # Create EmployeeProfile if not exists
        profile = getattr(user, 'employee_profile', None)
        if not profile:
            from decimal import Decimal
            profile = EmployeeProfile.objects.create(
                user=user,
                department=offer.department,
                designation=offer.designation,
                basic_salary=offer.basic_salary or Decimal('0'),
                date_of_joining=offer.date_of_joining,
                probation_status=offer.probation_status,
                onboarding_status='PENDING',
                is_active=False,
                is_locked=True,
            )
        else:
            profile.department    = offer.department
            profile.designation   = offer.designation
            profile.basic_salary  = offer.basic_salary
            profile.date_of_joining = offer.date_of_joining
            profile.probation_status = offer.probation_status
            profile.save()

        # Link profile to offer
        offer.profile    = profile
        offer.is_accepted = True
        offer.accepted_at = timezone.now()
        offer.save()

        # Notify all HR users via InternalMail
        hr_users = User.objects.filter(role=User.Role.HR, is_active=True)
        body = (
            f"Dear HR Team,\n\n"
            f"{first_name} {last_name} ({email}) has formally accepted the offer for "
            f"{offer.designation} in the {offer.department} department.\n\n"
            f"Joining Date: {offer.date_of_joining.strftime('%B %d, %Y') if offer.date_of_joining else 'TBD'}\n"
            f"Salary: ₹{offer.basic_salary}\n\n"
            f"Their employee profile has been created automatically. Please review and activate their account.\n\n"
            f"Regards,\n{first_name} {last_name}"
        )
        for hr_user in hr_users:
            InternalMail.objects.create(
                sender_name=f"{first_name} {last_name}",
                sender_email=email,
                recipient=hr_user,
                subject=f"Offer Accepted – {first_name} {last_name} ({offer.designation})",
                body=body,
                mail_type='OFFER_ACCEPTANCE',
                related_offer=offer,
            )

        return render(request, 'communications/offer_accepted_thanks.html', {
            'offer': offer,
            'candidate_name': f"{first_name} {last_name}",
        })

    return render(request, 'communications/offer_accept.html', {'offer': offer})


# ─────────────────────────────────────────────
# HR: VERIFY ACCEPTANCE → activate employee
# ─────────────────────────────────────────────
@hr_only
def verify_acceptance(request, mail_id):
    mail = get_object_or_404(InternalMail, id=mail_id, mail_type='OFFER_ACCEPTANCE')
    offer = mail.related_offer

    if not offer or not offer.profile:
        messages.error(request, "No candidate profile is linked to this acceptance mail yet.")
        return redirect('communications:mail_detail', mail_id=mail_id)

    if mail.is_verified:
        messages.warning(request, "This acceptance has already been verified.")
        return redirect('communications:mail_detail', mail_id=mail_id)

    if request.method == 'POST':
        profile = offer.profile
        
        # Generate unique Employee ID
        if not profile.employee_id:
            import uuid
            dept_code = profile.department.code if profile.department and profile.department.code else "GEN"
            employee_id = f"AEC-{dept_code}-{uuid.uuid4().hex[:6].upper()}"
            profile.employee_id = employee_id
        else:
            employee_id = profile.employee_id

        # Username: the employee's name (lowercase, spaces replaced by underscore, unique)
        import re
        name_str = f"{profile.user.first_name}_{profile.user.last_name}"
        username = re.sub(r'[^a-zA-Z0-9_]', '', name_str.replace(' ', '_')).lower()

        original_username = username
        counter = 1
        while User.objects.filter(username=username).exclude(id=profile.user.id).exists():
            username = f"{original_username}{counter}"
            counter += 1

        profile.is_active = True
        profile.onboarding_status = 'COMPLETED'
        profile.save()

        profile.user.username = username
        profile.user.set_password(employee_id)
        profile.user.is_active = True
        profile.user.save()

        # Mark all acceptance mails for this offer as verified
        InternalMail.objects.filter(
            related_offer=offer,
            mail_type='OFFER_ACCEPTANCE',
        ).update(is_verified=True)

        try:
            from core.wishes_service import trigger_onboarding_wish
            trigger_onboarding_wish(profile)
        except Exception:
            pass

        # Save credentials in session so dashboard can display a nice copyable popup/banner
        request.session['new_staff_creds'] = {
            'name': profile.user.get_full_name(),
            'username': username,
            'password': employee_id,
            'dept': profile.department.name if profile.department else "General",
            'pos': profile.designation,
        }

        messages.success(
            request,
            f"✅ {profile.user.get_full_name()} activated as employee (ID: {profile.employee_id})."
        )
        return redirect('onboarding:onboarding_dashboard')

    return render(request, 'communications/verify_acceptance.html', {
        'mail': mail,
        'offer': offer,
        'profile': offer.profile,
    })


# ─────────────────────────────────────────────
# GENERATE PROMOTION LETTER
# ─────────────────────────────────────────────
@login_required
@user_passes_test(is_hr_or_md)
def generate_promotion_letter(request):
    from .forms import PromotionForm

    if request.method == 'POST':
        form = PromotionForm(request.POST)
        if form.is_valid():
            employee        = form.cleaned_data['employee']
            new_designation = form.cleaned_data['new_designation']
            new_salary      = form.cleaned_data['new_salary']
            effective_date  = form.cleaned_data['effective_date']

            employee.designation  = new_designation
            employee.basic_salary = new_salary
            employee.save()

            body = (
                f"Dear {employee.user.get_full_name()},\n\n"
                f"We are pleased to inform you that, effective {effective_date.strftime('%B %d, %Y')}, "
                f"you have been promoted to the position of {new_designation} in the "
                f"{employee.department.name} department.\n\n"
                f"Your revised monthly basic salary will be ₹{new_salary}.\n\n"
                f"We congratulate you on this well-deserved recognition and look forward to your "
                f"continued contributions to AEC Group.\n\n"
                f"Regards,\nHuman Resources\nAEC Group"
            )
            InternalMail.objects.create(
                sender=request.user,
                recipient=employee.user,
                recipient_email=employee.user.email,
                subject=f"Promotion Letter – {new_designation}",
                body=body,
                mail_type='PROMOTION',
            )

            def send_promo_mail():
                try:
                    from django.core.mail import send_mail
                    from django.conf import settings
                    send_mail(
                        subject=f"Promotion Letter – {new_designation}",
                        message=body,
                        from_email=settings.DEFAULT_FROM_EMAIL,
                        recipient_list=[employee.user.email],
                        fail_silently=False,
                    )
                except Exception as e:
                    print(f"Background promo email failed: {e}")

            import threading
            threading.Thread(target=send_promo_mail, daemon=True).start()

            try:
                from core.wishes_service import trigger_promotion_wish
                trigger_promotion_wish(employee, new_designation)
            except Exception:
                pass

            messages.success(
                request,
                f"Promotion letter for {employee.user.get_full_name()} sent successfully."
            )
            return redirect('communications:send_promotion')
    else:
        form = PromotionForm()

    return render(request, 'communications/generate_promotion.html', {'form': form})
