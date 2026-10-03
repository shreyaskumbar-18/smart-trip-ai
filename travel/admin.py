from django.contrib import admin
from .models import *
for model in [Profile,Destination,Attraction,Trip,ItineraryItem,RecommendationFeedback,SavedTrip,
              BudgetExpense,GroupTrip,WhatIfScenario,TripReplanLog]:
    admin.site.register(model)
