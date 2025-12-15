from django import forms

from .models import Motion


class MotionForm(forms.ModelForm):
    class Meta:
        model = Motion
        fields = [
            "title",
            "body",
            "display_order",
            "allow_vote_change",
            "reveal_results",
            "auto_close_seconds",
        ]
        widgets = {
            "body": forms.Textarea(attrs={"rows": 4}),
        }

    def clean_auto_close_seconds(self):
        value = self.cleaned_data.get("auto_close_seconds")
        if value is not None and value <= 0:
            raise forms.ValidationError("Auto-close must be greater than zero seconds.")
        return value
