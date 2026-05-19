from django import forms
from .models import InviteToken
from core.models import Department, EmployeeProfile

FIELD_CLASS = 'w-full border border-slate-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400'

class HRInviteForm(forms.ModelForm):
    department = forms.ModelChoiceField(
        queryset=Department.objects.filter(is_active=True),
        empty_label="Select Department",
        widget=forms.Select(attrs={'class': FIELD_CLASS})
    )
    class Meta:
        model = InviteToken
        fields = ['email', 'department']
        widgets = {
            'email': forms.EmailInput(attrs={'class': FIELD_CLASS, 'placeholder': 'candidate@example.com'})
        }


class OfferLetterForm(forms.ModelForm):
    department = forms.ModelChoiceField(
        queryset=Department.objects.filter(is_active=True),
        empty_label="Select Department",
        widget=forms.Select(attrs={'class': FIELD_CLASS, 'id': 'id_department'})
    )
    duties = forms.CharField(widget=forms.Textarea(attrs={'class': FIELD_CLASS, 'rows': 4}))
    probation_status = forms.ChoiceField(
        choices=[
            ('PROBATION', 'Probation'),
            ('PERMANENT', 'Permanent'),
            ('TRAINEE', 'Trainee'),
            ('INTERN', 'Intern')
        ],
        label="Employment Type",
        widget=forms.Select(attrs={'class': FIELD_CLASS, 'id': 'id_employment_type'})
    )
    probation_duration = forms.CharField(
        required=False, 
        label="Duration",
        widget=forms.TextInput(attrs={'class': FIELD_CLASS, 'placeholder': 'e.g. 3 Months, 6 Months', 'id': 'id_duration'})
    )
    additional_notes = forms.CharField(required=False, label="Additional HR Messages",
        widget=forms.Textarea(attrs={'class': FIELD_CLASS, 'rows': 3}))

    class Meta:
        model = EmployeeProfile
        fields = ['department', 'designation', 'probation_status', 'basic_salary', 'date_of_joining']
        widgets = {
            'designation':      forms.TextInput(attrs={'class': FIELD_CLASS}),
            'basic_salary':     forms.NumberInput(attrs={'class': FIELD_CLASS}),
            'date_of_joining':  forms.DateInput(attrs={'type': 'date', 'class': FIELD_CLASS}),
        }


class CandidateOnboardingForm(forms.Form):
    # ── Personal ──────────────────────────────────
    first_name  = forms.CharField(max_length=50,  widget=forms.TextInput(attrs={'class': FIELD_CLASS}))
    last_name   = forms.CharField(max_length=50,  widget=forms.TextInput(attrs={'class': FIELD_CLASS}))
    date_of_birth = forms.DateField(required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'class': FIELD_CLASS}))
    gender      = forms.ChoiceField(required=False,
        choices=[('','— Select —'),('Male','Male'),('Female','Female'),('Other','Other')],
        widget=forms.Select(attrs={'class': FIELD_CLASS}))
    phone       = forms.CharField(max_length=15,  widget=forms.TextInput(attrs={'class': FIELD_CLASS}))
    address     = forms.CharField(required=False,
        widget=forms.Textarea(attrs={'class': FIELD_CLASS, 'rows': 2}))

    # ── Identity ──────────────────────────────────
    aadhaar     = forms.CharField(max_length=12, label="Aadhaar Number",
        widget=forms.TextInput(attrs={'class': FIELD_CLASS, 'placeholder': 'Last 4 digits stored masked'}))
    pan_number  = forms.CharField(max_length=10, required=False, label="PAN Card Number",
        widget=forms.TextInput(attrs={'class': FIELD_CLASS + ' uppercase', 'placeholder': 'ABCDE1234F'}))

    # ── Emergency Contact ─────────────────────────
    emergency_contact_name  = forms.CharField(max_length=100, required=False, label="Emergency Contact Name",
        widget=forms.TextInput(attrs={'class': FIELD_CLASS}))
    emergency_contact_rel   = forms.ChoiceField(required=False, label="Relationship",
        choices=[('','— Select —'),('Spouse','Spouse'),('Parent','Parent'),
                 ('Sibling','Sibling'),('Child','Child'),('Friend','Friend'),('Other','Other')],
        widget=forms.Select(attrs={'class': FIELD_CLASS}))
    emergency_contact_phone = forms.CharField(max_length=15, required=False, label="Emergency Contact Phone",
        widget=forms.TextInput(attrs={'class': FIELD_CLASS}))

    # ── Personal Bank Account ─────────────────────
    personal_bank_name   = forms.CharField(max_length=100, required=False, label="Personal Bank Name",
        widget=forms.TextInput(attrs={'class': FIELD_CLASS, 'placeholder': 'e.g. State Bank of India'}))
    personal_branch_name = forms.CharField(max_length=100, required=False, label="Personal Branch Name",
        widget=forms.TextInput(attrs={'class': FIELD_CLASS, 'placeholder': 'e.g. MG Road Branch'}))
    personal_ifsc        = forms.CharField(max_length=11, required=False, label="Personal IFSC Code",
        widget=forms.TextInput(attrs={'class': FIELD_CLASS + ' uppercase font-mono', 'placeholder': 'SBIN0001234'}))
    personal_account     = forms.CharField(max_length=30, required=False, label="Personal Account Number",
        widget=forms.TextInput(attrs={'class': FIELD_CLASS + ' font-mono'}))

    # ── Salary Bank Account ───────────────────────
    salary_bank_name     = forms.CharField(max_length=100, required=False, label="Salary Bank Name",
        widget=forms.TextInput(attrs={'class': FIELD_CLASS, 'placeholder': 'e.g. HDFC Bank'}))
    salary_branch_name   = forms.CharField(max_length=100, required=False, label="Salary Branch Name",
        widget=forms.TextInput(attrs={'class': FIELD_CLASS, 'placeholder': 'e.g. Anna Nagar Branch'}))
    salary_ifsc          = forms.CharField(max_length=11, required=False, label="Salary IFSC Code",
        widget=forms.TextInput(attrs={'class': FIELD_CLASS + ' uppercase font-mono', 'placeholder': 'HDFC0001234'}))
    salary_account       = forms.CharField(max_length=30, required=False, label="Salary Account Number",
        widget=forms.TextInput(attrs={'class': FIELD_CLASS + ' font-mono'}))


    # ── Documents ─────────────────────────────────
    profile_pic       = forms.ImageField(required=True,
        widget=forms.FileInput(attrs={'class': FIELD_CLASS, 'id': 'profile_pic_input', 'accept': 'image/*'}))
    id_proof          = forms.FileField(required=True, label="ID Proof (Aadhaar/PAN)",
        widget=forms.FileInput(attrs={'class': FIELD_CLASS}))
    academic_doc      = forms.FileField(required=True, label="Highest Academic Certificate",
        widget=forms.FileInput(attrs={'class': FIELD_CLASS}))
    certificate_10th  = forms.FileField(required=False, label="10th Class Certificate",
        widget=forms.FileInput(attrs={'class': FIELD_CLASS}))
    certificate_12th  = forms.FileField(required=False, label="+2 / 12th Certificate",
        widget=forms.FileInput(attrs={'class': FIELD_CLASS}))
    certificate_degree= forms.FileField(required=False, label="Degree Certificate",
        widget=forms.FileInput(attrs={'class': FIELD_CLASS}))
    other_certificates= forms.FileField(required=False, label="Other Certificates",
        widget=forms.FileInput(attrs={'class': FIELD_CLASS}))
    exp_letter        = forms.FileField(required=False, label="Experience Letter (if any)",
        widget=forms.FileInput(attrs={'class': FIELD_CLASS}))
    salary_slips      = forms.FileField(required=False, label="Previous Salary Slips (if any)",
        widget=forms.FileInput(attrs={'class': FIELD_CLASS}))

