from django.contrib.auth.models import User
from django.db import models


class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    home_city = models.CharField(max_length=120, blank=True)
    preferred_budget = models.PositiveIntegerField(default=20000)
    travel_style = models.CharField(max_length=60, default="balanced")
    interests = models.CharField(max_length=255, default="culture,nature,food")
    group_size = models.PositiveIntegerField(default=1)
    sustainability_priority = models.PositiveIntegerField(default=3)
    email_verified = models.BooleanField(default=False)

    def __str__(self):
        return self.user.username


class UserPreference(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="preference")
    culture = models.FloatField(default=0.5)
    nature = models.FloatField(default=0.5)
    adventure = models.FloatField(default=0.5)
    food = models.FloatField(default=0.5)
    history = models.FloatField(default=0.5)
    shopping = models.FloatField(default=0.5)
    relaxation = models.FloatField(default=0.5)
    hidden_gems = models.FloatField(default=0.5)
    sustainability = models.FloatField(default=0.5)
    feedback_count = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    def as_dict(self):
        return {
            "culture": self.culture,
            "nature": self.nature,
            "adventure": self.adventure,
            "food": self.food,
            "history": self.history,
            "shopping": self.shopping,
            "relaxation": self.relaxation,
        }

    def __str__(self):
        return f"Preferences: {self.user.username}"


class OTPVerification(models.Model):
    PURPOSES = [
        ("register", "Registration"),
        ("login", "Passwordless Login"),
        ("reset", "Password Reset"),
    ]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="otp_codes")
    purpose = models.CharField(max_length=20, choices=PURPOSES)
    code_hash = models.CharField(max_length=128)
    expires_at = models.DateTimeField()
    attempts = models.PositiveIntegerField(default=0)
    used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user.username} {self.purpose}"


class Destination(models.Model):
    name = models.CharField(max_length=120)
    state = models.CharField(max_length=120)
    description = models.TextField()
    image_url = models.URLField(blank=True)
    average_daily_cost = models.PositiveIntegerField(default=2000)
    best_for = models.CharField(max_length=255)
    rating = models.DecimalField(max_digits=3, decimal_places=1, default=4.5)
    sustainability_score = models.PositiveIntegerField(default=70)
    hidden_gem_score = models.PositiveIntegerField(default=50)
    safety_score = models.PositiveIntegerField(default=80)

    def __str__(self):
        return f"{self.name}, {self.state}"


class Attraction(models.Model):
    destination = models.ForeignKey(Destination, on_delete=models.CASCADE, related_name="attractions")
    name = models.CharField(max_length=150)
    category = models.CharField(max_length=80)
    description = models.TextField()
    estimated_cost = models.PositiveIntegerField(default=300)
    duration_hours = models.DecimalField(max_digits=4, decimal_places=1, default=2)
    crowd_level = models.PositiveIntegerField(default=50)
    sustainability_score = models.PositiveIntegerField(default=70)
    hidden_gem_score = models.PositiveIntegerField(default=50)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    tags = models.CharField(max_length=255, default="")

    def __str__(self):
        return self.name


class Review(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="reviews")
    destination = models.ForeignKey(Destination, on_delete=models.CASCADE, related_name="reviews")
    rating = models.PositiveSmallIntegerField()
    title = models.CharField(max_length=120, blank=True)
    body = models.TextField()
    helpful_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "destination"], name="unique_user_destination_review")
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.destination.name} - {self.rating}/5"


class Trip(models.Model):
    INTERESTS = [(x, x.title()) for x in ["culture", "nature", "adventure", "food", "history", "shopping", "relaxation"]]
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="trips")
    destination = models.ForeignKey(Destination, on_delete=models.CASCADE, related_name="trips")
    title = models.CharField(max_length=180)
    start_date = models.DateField()
    end_date = models.DateField()
    travelers = models.PositiveIntegerField(default=1)
    budget = models.PositiveIntegerField(default=10000)
    interest = models.CharField(max_length=30, choices=INTERESTS, default="culture")
    pace = models.CharField(max_length=20, choices=[("relaxed", "Relaxed"), ("balanced", "Balanced"), ("packed", "Packed")], default="balanced")
    sustainability_priority = models.PositiveIntegerField(default=3)
    include_hidden_gems = models.BooleanField(default=True)
    weather_adaptive = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def days(self):
        return max((self.end_date - self.start_date).days + 1, 1)

    @property
    def estimated_total(self):
        return self.days * self.destination.average_daily_cost * self.travelers

    def __str__(self):
        return self.title


class ItineraryItem(models.Model):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="items")
    day_number = models.PositiveIntegerField()
    attraction = models.ForeignKey(Attraction, on_delete=models.CASCADE)
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    score = models.FloatField(default=0)
    reason = models.CharField(max_length=500, blank=True)
    weather_alternative = models.ForeignKey(Attraction, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")

    def __str__(self):
        return f"{self.trip.title} Day {self.day_number}: {self.attraction.name}"


class RecommendationFeedback(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    attraction = models.ForeignKey(Attraction, on_delete=models.CASCADE)
    trip = models.ForeignKey(Trip, on_delete=models.SET_NULL, null=True, blank=True)
    action = models.CharField(max_length=20, choices=[("like", "Like"), ("dislike", "Dislike"), ("save", "Save"), ("skip", "Skip")])
    created_at = models.DateTimeField(auto_now_add=True)


class SavedTrip(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name="saved_trips")
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="saved_by")
    saved_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "trip"], name="unique_saved_trip")]


class BudgetExpense(models.Model):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="expenses")
    category = models.CharField(max_length=30)
    amount = models.PositiveIntegerField()
    description = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class GroupTrip(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name="owned_group_trips")
    trip = models.OneToOneField(Trip, on_delete=models.CASCADE, related_name="group")
    invite_code = models.CharField(max_length=30, unique=True)
    members = models.ManyToManyField(User, related_name="group_trips", blank=True)

    def __str__(self):
        return self.trip.title


class WhatIfScenario(models.Model):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="scenarios")
    name = models.CharField(max_length=120)
    budget_change = models.IntegerField(default=0)
    extra_days = models.IntegerField(default=0)
    preferred_interest = models.CharField(max_length=30, blank=True)
    result_summary = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class TripReplanLog(models.Model):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name="replan_logs")
    trigger = models.CharField(max_length=120)
    action = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
