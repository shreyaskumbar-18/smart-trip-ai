from django.contrib import admin
from .models import (
    Profile, UserPreference, OTPVerification, Destination, Attraction,
    Review, Trip, ItineraryItem, RecommendationFeedback, SavedTrip,
    BudgetExpense, GroupTrip, WhatIfScenario, TripReplanLog
)

admin.site.register([
    Profile, UserPreference, OTPVerification, Destination, Attraction,
    Review, Trip, ItineraryItem, RecommendationFeedback, SavedTrip,
    BudgetExpense, GroupTrip, WhatIfScenario, TripReplanLog
])
