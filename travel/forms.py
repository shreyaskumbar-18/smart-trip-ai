from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from .models import (
    BudgetExpense,
    Profile,
    Trip,
    WhatIfScenario,
)


class RegisterForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = (
            "username",
            "email",
            "password1",
            "password2",
        )


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
        travelers = cleaned.get("travelers")
        budget = cleaned.get("budget")

        if start and end and end < start:
            self.add_error(
                "end_date",
                "End date must be on or after the start date.",
            )

        if travelers is not None and travelers < 1:
            self.add_error(
                "travelers",
                "Travelers must be at least 1.",
            )

        if budget is not None and budget < 0:
            self.add_error(
                "budget",
                "Budget cannot be negative.",
            )

        return cleaned


class ExpenseForm(forms.ModelForm):
    class Meta:
        model = BudgetExpense
        fields = (
            "category",
            "amount",
            "description",
        )

        widgets = {
            "amount": forms.NumberInput(attrs={"min": 1}),
        }


class ScenarioForm(forms.ModelForm):
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
