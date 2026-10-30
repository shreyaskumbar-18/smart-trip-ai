
from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.utils import timezone
from decimal import Decimal

from .models import (
    BudgetExpense,
    Profile,
    Review,
    Trip,
    WhatIfScenario,
)


class RegisterForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ("username", "email", "password1", "password2")

    def clean_email(self):
        email = self.cleaned_data["email"].strip().lower()

        # Active accounts cannot register with the same email.
        if User.objects.filter(
            email__iexact=email,
            is_active=True,
        ).exists():
            raise forms.ValidationError(
                "An account with this email already exists."
            )

        # An inactive account may resume registration.
        return email


class ProfileForm(forms.ModelForm):
    class Meta:
        model = Profile
        fields = (
            "home_city",
            "preferred_budget",
            "travel_style",
            "interests",
            "group_size",
            "sustainability_priority",
        )
        widgets = {
            "preferred_budget": forms.NumberInput(attrs={"min": 0}),
            "group_size": forms.NumberInput(attrs={"min": 1}),
            "sustainability_priority": forms.NumberInput(
                attrs={"min": 0, "max": 10}
            ),
        }


class TripForm(forms.ModelForm):
    trip_brief = forms.CharField(
        required=False,
        label="Describe your trip (optional AI assist)",
        widget=forms.Textarea(
            attrs={
                "rows": 3,
                "placeholder": (
                    "Example: Plan 3 days in Goa under ₹12000 "
                    "for 2 travellers. I like beaches and food."
                ),
                "class": "form-control",
            }
        ),
        help_text=(
            "Describe your trip in plain English. SmartTrip will "
            "prefill the form; review dates and budget before generating."
        ),
    )

    class Meta:
        model = Trip
        fields = (
            "destination",
            "title",
            "start_date",
            "end_date",
            "travelers",
            "budget",
            "interest",
            "pace",
            "sustainability_priority",
            "include_hidden_gems",
            "weather_adaptive",
        )
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
            "travelers": forms.NumberInput(attrs={"min": 1}),
            "budget": forms.NumberInput(attrs={"min": 0}),
            "sustainability_priority": forms.NumberInput(
                attrs={"min": 0, "max": 10}
            ),
        }

    def clean(self):
        cleaned = super().clean()
        start = cleaned.get("start_date")
        end = cleaned.get("end_date")

        if start and end and end < start:
            self.add_error(
                "end_date",
                "End date must be on or after the start date.",
            )

        travelers = cleaned.get("travelers")
        if travelers is not None and travelers < 1:
            self.add_error(
                "travelers",
                "Travelers must be at least 1.",
            )
        if travelers is not None and travelers > 50:
            self.add_error("travelers", "Trips can include at most 50 travelers.")

        priority = cleaned.get("sustainability_priority")
        if priority is not None and not 0 <= priority <= 10:
            self.add_error("sustainability_priority", "Choose a value from 0 to 10.")

        if start and start < timezone.localdate():
            self.add_error("start_date", "Trip start date cannot be in the past.")

        budget = cleaned.get("budget")
        if budget is not None and budget < 0:
            self.add_error(
                "budget",
                "Budget cannot be negative.",
            )

        return cleaned


EXPENSE_CATEGORIES = [
    ("Accommodation", "Accommodation & Stay"),
    ("Food", "Food & Dining"),
    ("Transport", "Transport & Flights"),
    ("Activities", "Activities & Sightseeing"),
    ("Shopping", "Shopping & Souvenirs"),
    ("Miscellaneous", "Miscellaneous"),
]


class ExpenseForm(forms.ModelForm):
    amount = forms.DecimalField(
        min_value=Decimal("0.01"),
        max_digits=12,
        decimal_places=2,
        widget=forms.NumberInput(attrs={"min": "0.01", "step": "0.01", "class": "form-control rounded-pill", "placeholder": "Amount in ₹"}),
    )
    category = forms.ChoiceField(
        choices=EXPENSE_CATEGORIES,
        widget=forms.Select(attrs={"class": "form-select rounded-pill"}),
    )

    class Meta:
        model = BudgetExpense
        fields = ("category", "amount", "description")
        widgets = {
            "description": forms.TextInput(attrs={"class": "form-control rounded-pill", "placeholder": "e.g. Hotel reservation, Taxi, Museum entry"}),
        }


class BudgetAllocationForm(forms.Form):
    _number_widget = forms.NumberInput(attrs={"min": 0, "max": 100, "class": "form-control"})
    accommodation_budget_pct = forms.IntegerField(min_value=0, max_value=100, label="Accommodation", widget=_number_widget)
    food_budget_pct = forms.IntegerField(min_value=0, max_value=100, label="Food", widget=_number_widget)
    transport_budget_pct = forms.IntegerField(min_value=0, max_value=100, label="Transport", widget=_number_widget)
    activities_budget_pct = forms.IntegerField(min_value=0, max_value=100, label="Activities", widget=_number_widget)
    miscellaneous_budget_pct = forms.IntegerField(min_value=0, max_value=100, label="Miscellaneous", widget=_number_widget)

    def __init__(self, *args, trip=None, **kwargs):
        self.trip = trip
        has_no_bound_data = not args or args[0] is None
        if trip is not None and has_no_bound_data and "initial" not in kwargs:
            kwargs["initial"] = {
                name: getattr(trip, name)
                for name in self.base_fields
            }
        super().__init__(*args, **kwargs)

    def clean(self):
        cleaned = super().clean()
        if len(cleaned) == len(self.fields) and sum(cleaned.values()) != 100:
            raise forms.ValidationError("Budget allocations must total exactly 100%.")
        return cleaned

    def save(self):
        if self.trip is None or not self.is_valid():
            raise ValueError("A valid form and trip are required.")
        for name, value in self.cleaned_data.items():
            setattr(self.trip, name, value)
        self.trip.save(update_fields=list(self.cleaned_data))
        return self.trip


class ScenarioForm(forms.ModelForm):
    preferred_interest = forms.ChoiceField(
        required=False,
        label="Preferred interest",
        choices=[("", "Keep current interest")] + Trip.INTERESTS,
    )
    pace = forms.ChoiceField(
        required=False,
        label="Travel pace",
        choices=[("", "Keep current pace")] + Trip._meta.get_field("pace").choices,
    )

    class Meta:
        model = WhatIfScenario
        fields = (
            "name",
            "budget_change",
            "extra_days",
            "preferred_interest",
        )
        widgets = {
            "extra_days": forms.NumberInput(attrs={"min": 0}),
        }


class ReviewForm(forms.ModelForm):
    rating = forms.TypedChoiceField(
        choices=[
            (i, f"{i} Star" + ("" if i == 1 else "s"))
            for i in range(1, 6)
        ],
        coerce=int,
        empty_value=None,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    class Meta:
        model = Review
        fields = ("rating", "title", "body")
        widgets = {
            "title": forms.TextInput(
                attrs={"placeholder": "Short review title", "class": "form-control"}
            ),
            "body": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": "Share your experience",
                    "class": "form-control",
                }
            ),
        }

    def clean_rating(self):
        rating = self.cleaned_data.get("rating")
        if rating is None or rating < 1 or rating > 5:
            raise forms.ValidationError("Rating must be an integer between 1 and 5.")
        return rating
