from django import forms
from core.models import EmployeeProfile, Department

_inp  = 'w-full px-3 py-2 border border-slate-200 rounded-lg text-sm text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-400 bg-white mt-1'
_sel  = 'w-full px-3 py-2 border border-slate-200 rounded-lg text-sm text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-400 bg-white mt-1'
_ta   = 'w-full px-3 py-2 border border-slate-200 rounded-lg text-sm text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-400 bg-white mt-1 h-28 resize-none'
_date = 'w-full px-3 py-2 border border-slate-200 rounded-lg text-sm text-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-400 bg-white mt-1'

_em_sel  = 'w-full px-3 py-2 border border-slate-200 rounded-lg text-sm text-slate-700 focus:outline-none focus:ring-2 focus:ring-emerald-400 bg-white mt-1'
_em_inp  = 'w-full px-3 py-2 border border-slate-200 rounded-lg text-sm text-slate-700 focus:outline-none focus:ring-2 focus:ring-emerald-400 bg-white mt-1'


class OfferLetterForm(forms.Form):
    candidate_name = forms.CharField(
        max_length=200,
        widget=forms.TextInput(attrs={'class': _inp, 'placeholder': 'e.g. Rahul Sharma'})
    )
    candidate_email = forms.EmailField(
        widget=forms.EmailInput(attrs={'class': _inp, 'placeholder': 'candidate@email.com'})
    )
    department = forms.ModelChoiceField(
        queryset=Department.objects.filter(is_active=True),
        empty_label='— Select Department —',
        widget=forms.Select(attrs={'class': _sel})
    )
    designation = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={'class': _inp, 'placeholder': 'e.g. Software Engineer'})
    )
    PROBATION_CHOICES = [('PROBATION', 'Probation'), ('PERMANENT', 'Permanent')]
    probation_status = forms.ChoiceField(
        choices=PROBATION_CHOICES,
        widget=forms.Select(attrs={'class': _sel})
    )
    basic_salary = forms.DecimalField(
        max_digits=10, decimal_places=2,
        widget=forms.NumberInput(attrs={'class': _inp, 'placeholder': '0.00', 'min': '0', 'step': '0.01'})
    )
    date_of_joining = forms.DateField(
        required=False,
        widget=forms.DateInput(attrs={'type': 'date', 'class': _date})
    )
    probation_duration = forms.CharField(
        max_length=50, required=False,
        widget=forms.TextInput(attrs={'class': _inp, 'placeholder': 'e.g. 3 months'})
    )
    duties = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': _ta, 'placeholder': 'List key responsibilities…'})
    )
    additional_notes = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': _ta, 'placeholder': 'Any additional information…'})
    )


class PromotionForm(forms.Form):
    employee = forms.ModelChoiceField(
        queryset=EmployeeProfile.objects.filter(is_active=True, probation_status__in=['PROBATION', 'PERMANENT']),
        empty_label='— Select an employee —',
        widget=forms.Select(attrs={'class': _em_sel})
    )
    new_designation = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={'class': _em_inp, 'placeholder': 'e.g. Senior Manager'})
    )
    new_salary = forms.DecimalField(
        max_digits=10, decimal_places=2,
        widget=forms.NumberInput(attrs={'class': _em_inp, 'placeholder': '0.00', 'min': '0', 'step': '0.01'})
    )
    effective_date = forms.DateField(
        widget=forms.DateInput(attrs={'type': 'date', 'class': _date})
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['employee'].label_from_instance = lambda obj: (
            f"{obj.user.get_full_name()} — {obj.department.name} ({obj.designation or 'No designation'})"
        )
