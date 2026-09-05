from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from .models import (ChecklistItem, Expense, INTEREST_CHOICES, ItineraryItem, Trip,
                     TripJournal, UserProfile, Vote)


def _bootstrap(fields):
    for field in fields.values():
        widget = field.widget
        if isinstance(widget, (forms.CheckboxSelectMultiple, forms.CheckboxInput, forms.RadioSelect)):
            continue
        if isinstance(widget, forms.Select):
            widget.attrs.setdefault('class', 'form-select')
        else:
            widget.attrs.setdefault('class', 'form-control')


class RegisterForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ['username', 'email', 'password1', 'password2']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrap(self.fields)

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        if commit:
            user.save()
        return user


class LoginForm(forms.Form):
    username = forms.CharField()
    password = forms.CharField(widget=forms.PasswordInput)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrap(self.fields)


class UserProfileForm(forms.ModelForm):
    class Meta:
        model = UserProfile
        fields = ['profile_image', 'travel_style', 'preferred_activities',
                  'preferred_budget', 'preferred_destination_type']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrap(self.fields)


class TripForm(forms.ModelForm):
    interests = forms.MultipleChoiceField(choices=INTEREST_CHOICES,
                                          widget=forms.CheckboxSelectMultiple,
                                          required=True)

    class Meta:
        model = Trip
        fields = ['title', 'destination', 'start_date', 'end_date',
                  'total_budget', 'number_of_people', 'travel_style']
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrap(self.fields)

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get('start_date')
        end = cleaned.get('end_date')
        if start and end and start > end:
            self.add_error('end_date', 'End date cannot be before the start date.')
        budget = cleaned.get('total_budget')
        if budget is not None and budget <= 0:
            self.add_error('total_budget', 'Budget must be a positive amount.')
        people = cleaned.get('number_of_people')
        if people is not None and people <= 0:
            self.add_error('number_of_people', 'Number of travelers must be positive.')
        return cleaned


class ItineraryItemForm(forms.ModelForm):
    class Meta:
        model = ItineraryItem
        fields = ['day_number', 'place', 'start_time', 'end_time', 'notes']
        widgets = {
            'start_time': forms.TimeInput(attrs={'type': 'time'}),
            'end_time': forms.TimeInput(attrs={'type': 'time'}),
            'notes': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, trip=None, **kwargs):
        super().__init__(*args, **kwargs)
        if trip is not None:
            self.fields['place'].queryset = trip.destination.places.all()
        _bootstrap(self.fields)


class ExpenseForm(forms.ModelForm):
    class Meta:
        model = Expense
        fields = ['title', 'amount', 'category', 'date', 'description']
        widgets = {
            'date': forms.DateInput(attrs={'type': 'date'}),
            'description': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrap(self.fields)

    def clean_amount(self):
        amount = self.cleaned_data['amount']
        if amount <= 0:
            raise forms.ValidationError('Amount must be positive.')
        return amount


class VoteForm(forms.ModelForm):
    options_text = forms.CharField(
        label='Options (one per line)',
        widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'One option per line'}))

    class Meta:
        model = Vote
        fields = ['title', 'category', 'description']
        widgets = {'description': forms.Textarea(attrs={'rows': 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrap(self.fields)

    def clean_options_text(self):
        lines = [l.strip() for l in self.cleaned_data['options_text'].splitlines() if l.strip()]
        if len(lines) < 2:
            raise forms.ValidationError('Provide at least two options.')
        return lines


class JournalForm(forms.ModelForm):
    class Meta:
        model = TripJournal
        fields = ['title', 'content', 'image']
        widgets = {'content': forms.Textarea(attrs={'rows': 4})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrap(self.fields)


class ChecklistItemForm(forms.ModelForm):
    class Meta:
        model = ChecklistItem
        fields = ['title', 'category']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _bootstrap(self.fields)


class InviteForm(forms.Form):
    identifier = forms.CharField(label='Username or email',
                                 widget=forms.TextInput(attrs={'class': 'form-control',
                                                               'placeholder': 'friend_username or friend@email.com'}))
