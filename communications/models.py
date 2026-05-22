import uuid as _uuid
from django.db import models
from django.conf import settings


# ─────────────────────────────────────────────────────────────
# Internal Mail  (inbox / sent between HR, MD, Staff)
# ─────────────────────────────────────────────────────────────
class InternalMail(models.Model):
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sent_mails',
        null=True, blank=True
    )
    # For mails sent by external candidates (no User account yet)
    sender_name  = models.CharField(max_length=200, blank=True)
    sender_email = models.EmailField(blank=True)

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='received_mails',
        null=True, blank=True
    )
    recipient_email = models.EmailField(blank=True, help_text="For external candidates")

    subject    = models.CharField(max_length=255)
    body       = models.TextField()
    is_read    = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    MAIL_TYPES = (
        ('GENERAL',          'General'),
        ('OFFER',            'Offer Letter'),
        ('APPOINTMENT',      'Appointment Letter'),
        ('PROMOTION',        'Promotion Letter'),
        ('OFFER_ACCEPTANCE', 'Offer Acceptance'),
        ('WISH',             'Wish'),
        ('LATE_WARNING',     'Late Warning'),
    )
    mail_type = models.CharField(max_length=20, choices=MAIL_TYPES, default='GENERAL')

    # Link to OfferLetter for acceptance tracking
    related_offer = models.ForeignKey(
        'OfferLetter',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='acceptance_mails',
    )
    # True once HR has clicked "Verify" on an acceptance mail
    is_verified = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.subject

    @property
    def display_sender(self):
        if self.sender:
            return self.sender.get_full_name() or self.sender.username
        return self.sender_name or self.sender_email or 'Candidate'

    @property
    def display_sender_email(self):
        if self.sender:
            return self.sender.email
        return self.sender_email

    @property
    def related_profile(self):
        from core.models import EmployeeProfile
        if self.related_offer and self.related_offer.profile:
            return self.related_offer.profile
        email = self.sender_email
        if not email and self.related_offer:
            email = self.related_offer.candidate_email
        if email:
            profile = EmployeeProfile.objects.filter(user__email=email).order_by('-id').first()
            if profile:
                return profile
        return None


# ─────────────────────────────────────────────────────────────
# Offer Letter  (standalone HR-generated, email-first)
# ─────────────────────────────────────────────────────────────
class OfferLetter(models.Model):
    class ProbationStatus(models.TextChoices):
        PROBATION = 'PROBATION', 'Probation'
        PERMANENT = 'PERMANENT', 'Permanent'

    # Secure token used in the candidate-facing accept URL
    token = models.UUIDField(default=_uuid.uuid4, unique=True, editable=False)

    # Candidate info entered by HR (no User account required at this stage)
    candidate_name  = models.CharField(max_length=200)
    candidate_email = models.EmailField()

    # Job details
    department = models.ForeignKey(
        'core.Department',
        on_delete=models.SET_NULL,
        null=True, blank=True,
    )
    designation       = models.CharField(max_length=100)
    probation_status  = models.CharField(
        max_length=20,
        choices=ProbationStatus.choices,
        default=ProbationStatus.PROBATION,
    )
    basic_salary      = models.DecimalField(max_digits=10, decimal_places=2)
    date_of_joining   = models.DateField(null=True, blank=True)
    probation_duration = models.CharField(max_length=50, blank=True)
    duties            = models.TextField(blank=True)
    additional_notes  = models.TextField(blank=True)

    # Who sent it and when
    sent_by  = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='offer_letters_sent',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    is_sent    = models.BooleanField(default=False)

    # Acceptance tracking
    is_accepted = models.BooleanField(default=False)
    accepted_at = models.DateTimeField(null=True, blank=True)

    # Linked employee profile once the candidate accepts + HR verifies
    profile = models.OneToOneField(
        'core.EmployeeProfile',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='offer_letter',
    )

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Offer – {self.candidate_name} ({self.candidate_email})"
