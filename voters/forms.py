from django import forms
from .models import Voter , VotingSession

class VoterForm(forms.ModelForm):
    class Meta:
        model = Voter
        fields = ['Fname', 'Lname']
    
   
            
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
