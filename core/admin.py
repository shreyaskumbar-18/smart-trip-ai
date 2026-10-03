from django.contrib import admin

from .models import (ChecklistItem, Destination, Expense, ExpenseParticipant, Hotel,
                     ItineraryItem, Place, Recommendation, SavedTrip, Trip, TripJournal,
                     TripMember, UserProfile, Vote, VoteOption, VoteResponse)

admin.site.site_header = 'SmartTrip AI Administration'
admin.site.site_title = 'SmartTrip AI Admin'
admin.site.index_title = 'Manage SmartTrip AI'


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'travel_style', 'preferred_budget')
    search_fields = ('user__username',)


@admin.register(Destination)
class DestinationAdmin(admin.ModelAdmin):
    list_display = ('name', 'city', 'state', 'country', 'category', 'rating')
    list_filter = ('category', 'state')
    search_fields = ('name', 'city', 'state')


@admin.register(Place)
class PlaceAdmin(admin.ModelAdmin):
    list_display = ('name', 'destination', 'category', 'entry_fee', 'rating')
    list_filter = ('category', 'destination')
    search_fields = ('name',)


@admin.register(Hotel)
class HotelAdmin(admin.ModelAdmin):
    list_display = ('name', 'destination', 'price_per_night', 'rating')
    list_filter = ('destination',)
    search_fields = ('name',)


@admin.register(Trip)
class TripAdmin(admin.ModelAdmin):
    list_display = ('title', 'owner', 'destination', 'start_date', 'end_date', 'status')
    list_filter = ('status', 'destination')
    search_fields = ('title', 'owner__username')


@admin.register(TripMember)
class TripMemberAdmin(admin.ModelAdmin):
    list_display = ('trip', 'user', 'role', 'joined_at')
    list_filter = ('role',)


@admin.register(ItineraryItem)
class ItineraryItemAdmin(admin.ModelAdmin):
    list_display = ('trip', 'day_number', 'place', 'start_time', 'end_time', 'order')
    list_filter = ('trip',)


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ('trip', 'title', 'amount', 'category', 'paid_by', 'date')
    list_filter = ('category', 'trip')


@admin.register(ExpenseParticipant)
class ExpenseParticipantAdmin(admin.ModelAdmin):
    list_display = ('expense', 'user', 'share_amount')


@admin.register(Vote)
class VoteAdmin(admin.ModelAdmin):
    list_display = ('trip', 'title', 'status', 'created_by', 'deadline')
    list_filter = ('status',)


@admin.register(VoteOption)
class VoteOptionAdmin(admin.ModelAdmin):
    list_display = ('vote', 'option_name')


@admin.register(VoteResponse)
class VoteResponseAdmin(admin.ModelAdmin):
    list_display = ('vote', 'option', 'user')


@admin.register(Recommendation)
class RecommendationAdmin(admin.ModelAdmin):
    list_display = ('trip', 'place', 'score', 'created_at')


@admin.register(SavedTrip)
class SavedTripAdmin(admin.ModelAdmin):
    list_display = ('user', 'trip', 'saved_at')


@admin.register(TripJournal)
class TripJournalAdmin(admin.ModelAdmin):
    list_display = ('trip', 'user', 'title', 'created_at')


@admin.register(ChecklistItem)
class ChecklistItemAdmin(admin.ModelAdmin):
    list_display = ('trip', 'title', 'category', 'completed')
    list_filter = ('category', 'completed')
