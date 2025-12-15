from django import forms
from .models import Voter , VotingSession
import re

class VoterForm(forms.ModelForm):
    class Meta:
        model = Voter
        fields = ['Fname', 'Lname', 'email', 'phone_number']
        labels = {'Fname': '', 'Lname': '', 'email': '', 'phone_number': ''}
        widgets = {
            'Fname': forms.TextInput(attrs={'placeholder': 'First Name', 'aria-label': 'First Name'}),
            'Lname': forms.TextInput(attrs={'placeholder': 'Last Name', 'aria-label': 'Last Name'}),
            'email': forms.EmailInput(attrs={'placeholder': 'Email (optional)', 'aria-label': 'Email'}),
            'phone_number': forms.TextInput(attrs={'placeholder': 'Phone (optional)', 'aria-label': 'Phone'}),
        }

    @staticmethod
    def _normalize_name(value):
        value = (value or '').strip()
        value = ' '.join(value.split())
        return value

    def clean_Fname(self):
        value = self._normalize_name(self.cleaned_data.get('Fname'))
        if not value:
            raise forms.ValidationError('This field is required.')
        return value

    def clean_email(self):
        email = (self.cleaned_data.get('email') or '').strip()
        return email or None

    def clean_phone_number(self):
        raw = (self.cleaned_data.get('phone_number') or '').strip()
        if not raw:
            return ''
        normalized = re.sub(r'[^\d+]', '', raw)
        return normalized

    def clean_Lname(self):
        value = self._normalize_name(self.cleaned_data.get('Lname'))
        if not value:
            raise forms.ValidationError('This field is required.')
        return value

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.Fname = self.cleaned_data['Fname']
        instance.Lname = self.cleaned_data['Lname']
        instance.email = self.cleaned_data.get('email')
        instance.phone_number = self.cleaned_data.get('phone_number', '')
        # Ensure admin/manual entries are immediately approved
        instance.registration_source = Voter.SOURCE_ADMIN
        instance.registration_status = Voter.STATUS_APPROVED
        if commit:
            instance.save()
        return instance

class VotingSessionForm(forms.ModelForm):
    class Meta:
        model = VotingSession
        fields = ['title']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'session-title-input',
                'placeholder': 'Enter New session title'
            }),
        }
