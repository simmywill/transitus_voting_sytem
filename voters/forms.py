from django import forms
from .models import Voter , VotingSession

class VoterForm(forms.ModelForm):
    class Meta:
        model = Voter
        fields = ['Fname', 'Lname']
        labels = {'Fname': '', 'Lname': ''}
        widgets = {
            'Fname': forms.TextInput(attrs={'placeholder': 'First Name', 'aria-label': 'First Name'}),
            'Lname': forms.TextInput(attrs={'placeholder': 'Last Name', 'aria-label': 'Last Name'}),
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

    def clean_Lname(self):
        value = self._normalize_name(self.cleaned_data.get('Lname'))
        if not value:
            raise forms.ValidationError('This field is required.')
        return value

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.Fname = self.cleaned_data['Fname']
        instance.Lname = self.cleaned_data['Lname']
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
