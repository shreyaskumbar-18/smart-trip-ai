from django.contrib.auth.models import User
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver

TRAVEL_STYLE_CHOICES = [
    ('Budget', 'Budget'), ('Balanced', 'Balanced'), ('Luxury', 'Luxury'),
    ('Adventure', 'Adventure'), ('Relaxed', 'Relaxed'), ('Family', 'Family'),
]

INTEREST_CHOICES = [
    ('Nature', 'Nature'), ('History', 'History'), ('Food', 'Food'),
    ('Shopping', 'Shopping'), ('Adventure', 'Adventure'), ('Beaches', 'Beaches'),
    ('Culture', 'Culture'), ('Photography', 'Photography'),
]

EXPENSE_CATEGORY_CHOICES = [
    ('Hotel', 'Hotel'), ('Food', 'Food'), ('Transport', 'Transport'),
    ('Activities', 'Activities'), ('Shopping', 'Shopping'), ('Other', 'Other'),
]

CHECKLIST_CATEGORY_CHOICES = [
    ('Essentials', 'Essentials'), ('Clothing', 'Clothing'), ('Electronics', 'Electronics'),
    ('Documents', 'Documents'), ('Medical', 'Medical'), ('Other', 'Other'),
]

TRIP_STATUS_CHOICES = [('Planning', 'Planning'), ('Ongoing', 'Ongoing'), ('Completed', 'Completed')]

OUTDOOR_CATEGORIES = {'Nature', 'Adventure', 'Beaches', 'Photography'}


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    profile_image = models.ImageField(upload_to='profiles/', blank=True, null=True)
    travel_style = models.CharField(max_length=20, choices=TRAVEL_STYLE_CHOICES, default='Balanced')
    preferred_activities = models.CharField(max_length=255, blank=True, help_text='Comma separated interests')
    preferred_budget = models.DecimalField(max_digits=10, decimal_places=2, default=20000)
    preferred_destination_type = models.CharField(max_length=50, blank=True)

    def interest_list(self):
        return [i.strip() for i in self.preferred_activities.split(',') if i.strip()]

    def __str__(self):
        return self.user.username + ' profile'


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)


class Destination(models.Model):
    name = models.CharField(max_length=100)
    city = models.CharField(max_length=100)
    state = models.CharField(max_length=100)
    country = models.CharField(max_length=100, default='India')
    description = models.TextField()
    image_url = models.URLField(blank=True)
    latitude = models.FloatField()
    longitude = models.FloatField()
    category = models.CharField(max_length=50)
    rating = models.FloatField(default=4.0)

    def __str__(self):
        return self.name


class Place(models.Model):
    name = models.CharField(max_length=120)
    destination = models.ForeignKey(Destination, on_delete=models.CASCADE, related_name='places')
    description = models.TextField(blank=True)
    category = models.CharField(max_length=30, choices=INTEREST_CHOICES)
    latitude = models.FloatField()
    longitude = models.FloatField()
    entry_fee = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    estimated_visit_time = models.FloatField(default=2.0, help_text='Hours')
    rating = models.FloatField(default=4.0)
    opening_time = models.TimeField(default='09:00')
    closing_time = models.TimeField(default='18:00')

    @property
    def is_outdoor(self):
        return self.category in OUTDOOR_CATEGORIES

    def __str__(self):
        return self.name


class Hotel(models.Model):
    name = models.CharField(max_length=120)
    destination = models.ForeignKey(Destination, on_delete=models.CASCADE, related_name='hotels')
    description = models.TextField(blank=True)
    price_per_night = models.DecimalField(max_digits=8, decimal_places=2)
    rating = models.FloatField(default=4.0)
    latitude = models.FloatField()
    longitude = models.FloatField()
    facilities = models.CharField(max_length=255, blank=True)
    image_url = models.URLField(blank=True)

    def __str__(self):
        return self.name


class Trip(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='owned_trips')
    title = models.CharField(max_length=150)
    destination = models.ForeignKey(Destination, on_delete=models.CASCADE, related_name='trips')
    start_date = models.DateField()
    end_date = models.DateField()
    total_budget = models.DecimalField(max_digits=12, decimal_places=2)
    number_of_people = models.PositiveIntegerField(default=1)
    travel_style = models.CharField(max_length=20, choices=TRAVEL_STYLE_CHOICES, default='Balanced')
    interests = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=15, choices=TRIP_STATUS_CHOICES, default='Planning')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    @property
    def duration_days(self):
        return (self.end_date - self.start_date).days + 1

    def interest_list(self):
        return [i.strip() for i in self.interests.split(',') if i.strip()]

    def __str__(self):
        return self.title


class TripMember(models.Model):
    ROLE_CHOICES = [('Owner', 'Owner'), ('Member', 'Member')]
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='members')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='trip_memberships')
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, default='Member')
    joined_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('trip', 'user')

    def __str__(self):
        return self.user.username + ' in ' + self.trip.title


class ItineraryItem(models.Model):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='itinerary_items')
    day_number = models.PositiveIntegerField()
    date = models.DateField()
    place = models.ForeignKey(Place, on_delete=models.CASCADE)
    start_time = models.TimeField()
    end_time = models.TimeField()
    order = models.PositiveIntegerField(default=1)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['day_number', 'order']

    def __str__(self):
        return self.trip.title + ' day ' + str(self.day_number) + ': ' + self.place.name


class Expense(models.Model):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='expenses')
    paid_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='expenses_paid')
    title = models.CharField(max_length=150)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    category = models.CharField(max_length=20, choices=EXPENSE_CATEGORY_CHOICES, default='Other')
    date = models.DateField()
    description = models.TextField(blank=True)

    class Meta:
        ordering = ['-date', '-id']

    def __str__(self):
        return self.title


class ExpenseParticipant(models.Model):
    expense = models.ForeignKey(Expense, on_delete=models.CASCADE, related_name='participants')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='expense_shares')
    share_amount = models.DecimalField(max_digits=10, decimal_places=2)

    def __str__(self):
        return self.user.username + ' owes ' + str(self.share_amount)


class Vote(models.Model):
    STATUS_CHOICES = [('Open', 'Open'), ('Closed', 'Closed')]
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='votes')
    title = models.CharField(max_length=150)
    category = models.CharField(max_length=50, blank=True)
    description = models.TextField(blank=True)
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='votes_created')
    deadline = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='Open')

    class Meta:
        ordering = ['-id']

    def total_responses(self):
        return VoteResponse.objects.filter(vote=self).count()

    def __str__(self):
        return self.title


class VoteOption(models.Model):
    vote = models.ForeignKey(Vote, on_delete=models.CASCADE, related_name='options')
    option_name = models.CharField(max_length=150)
    description = models.CharField(max_length=255, blank=True)

    def response_count(self):
        return self.responses.count()

    def __str__(self):
        return self.option_name


class VoteResponse(models.Model):
    vote = models.ForeignKey(Vote, on_delete=models.CASCADE, related_name='vote_responses')
    option = models.ForeignKey(VoteOption, on_delete=models.CASCADE, related_name='responses')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='vote_responses')

    class Meta:
        unique_together = ('vote', 'user')

    def __str__(self):
        return self.user.username + ' voted ' + self.option.option_name


class Recommendation(models.Model):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='recommendations')
    place = models.ForeignKey(Place, on_delete=models.CASCADE)
    score = models.FloatField()
    reason = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-score']

    def __str__(self):
        return self.place.name + ' (' + str(self.score) + ')'


class SavedTrip(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='saved_trips')
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='saved_by')
    saved_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'trip')

    def __str__(self):
        return self.user.username + ' saved ' + self.trip.title


class TripJournal(models.Model):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='journal_entries')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='journal_entries')
    title = models.CharField(max_length=150)
    content = models.TextField()
    image = models.ImageField(upload_to='journal/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title


class ChecklistItem(models.Model):
    trip = models.ForeignKey(Trip, on_delete=models.CASCADE, related_name='checklist_items')
    title = models.CharField(max_length=150)
    category = models.CharField(max_length=20, choices=CHECKLIST_CATEGORY_CHOICES, default='Essentials')
    completed = models.BooleanField(default=False)

    class Meta:
        ordering = ['completed', 'category', 'id']

    def __str__(self):
        return self.title
