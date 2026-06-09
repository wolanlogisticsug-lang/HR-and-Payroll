import uuid
from django.db import models
from django.utils import timezone
from datetime import timedelta
from core.models import Department, EmployeeProfile

class InviteToken(models.fields.related.ForeignKey):
    pass # To avoid circular import issues, although not really needed here if we import carefully.

class InviteToken(models.Model):
    class ProbationStatus(models.TextChoices):
        PROBATION = 'PROBATION', 'Probation'
        PERMANENT = 'PERMANENT', 'Permanent'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    candidate_name = models.CharField(max_length=100, blank=True)
    email = models.EmailField() # Removed unique=True to allow editing drafts/re-inviting
    department = models.ForeignKey(Department, on_delete=models.CASCADE)
    job_position = models.CharField(max_length=100, blank=True)
    probation_status = models.CharField(
        max_length=20, 
        choices=ProbationStatus.choices, 
        default=ProbationStatus.PROBATION
    )
    duties = models.TextField(blank=True)
    salary = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    joining_date = models.DateField(null=True, blank=True)
    
    is_draft = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    
    # Linked to profile once the candidate completes the form
    profile = models.OneToOneField(
        EmployeeProfile, 
        on_delete=models.SET_NULL, 
        null=True, blank=True,
        related_name='invite_token'
    )

    def save(self, *args, **kwargs):
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(days=7)
        super().save(*args, **kwargs)

    @property
    def is_valid(self):
        return not self.is_used and self.expires_at > timezone.now()

    def __str__(self):
        return f"{self.email} - {'Used' if self.is_used else 'Pending'}"
class BiometricDevice(models.Model):
    DEVICE_CHOICES = [
        ('zkteco', 'ZKTeco Terminal'),
        ('hikvision', 'Hikvision Terminal'),
    ]
    name = models.CharField(max_length=100, unique=True)
    device_type = models.CharField(max_length=20, choices=DEVICE_CHOICES)
    ip_address = models.GenericIPAddressField()
    port = models.IntegerField(default=4370)
    is_active = models.BooleanField(default=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} [{self.device_type}] - {self.ip_address}"