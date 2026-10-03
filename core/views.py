import json
from datetime import timedelta, time as dtime
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .algorithms import (dijkstra_shortest_path, fractional_knapsack, kmeans_cluster,
                         settle_expenses, tsp_optimize, weather_suitability)
from .forms import (ChecklistItemForm, ExpenseForm, InviteForm, ItineraryItemForm,
                    JournalForm, LoginForm, RegisterForm, TripForm, UserProfileForm,
                    VoteForm)
from .models import (ChecklistItem, Destination, Expense, ExpenseParticipant,
                     ItineraryItem, Place, Recommendation, SavedTrip, Trip, TripJournal,
                     TripMember, Vote, VoteOption, VoteResponse)
from .recommendations import recommend_places
from .services import (assistant_reply, compute_trip_score, get_currency_rates,
                       get_weather_forecast)

DEFAULT_CHECKLIST = [
    ('Passport / ID proof', 'Documents'), ('Tickets and bookings', 'Documents'),
    ('Phone charger and power bank', 'Electronics'), ('Camera', 'Electronics'),
    ('Comfortable footwear', 'Clothing'), ('Weather-appropriate clothes', 'Clothing'),
    ('Personal medicines', 'Medical'), ('First aid kit', 'Medical'),
    ('Toiletries', 'Essentials'), ('Cash and cards', 'Essentials'),
]

BUDGET_SPLITS = {
    'Budget':    [('Hotel', 28), ('Food', 25), ('Transport', 22), ('Activities', 15), ('Shopping', 5), ('Other', 5)],
    'Balanced':  [('Hotel', 35), ('Food', 22), ('Transport', 15), ('Activities', 18), ('Shopping', 6), ('Other', 4)],
    'Luxury':    [('Hotel', 45), ('Food', 20), ('Transport', 10), ('Activities', 15), ('Shopping', 7), ('Other', 3)],
    'Adventure': [('Hotel', 25), ('Food', 20), ('Transport', 18), ('Activities', 30), ('Shopping', 3), ('Other', 4)],
    'Relaxed':   [('Hotel', 42), ('Food', 24), ('Transport', 12), ('Activities', 12), ('Shopping', 6), ('Other', 4)],
    'Family':    [('Hotel', 38), ('Food', 26), ('Transport', 15), ('Activities', 12), ('Shopping', 5), ('Other', 4)],
}


def _get_trip(request, pk, owner_only=False):
    trip = get_object_or_404(Trip, pk=pk)
    if not trip.members.filter(user=request.user).exists():
        raise PermissionDenied('You are not a member of this trip.')
    if owner_only and trip.owner_id != request.user.id:
        raise PermissionDenied('Only the trip owner can perform this action.')
    return trip


def _total_spent(trip):
    return trip.expenses.aggregate(total=Sum('amount'))['total'] or Decimal('0')


# ---------------- Public pages ----------------

def home(request):
    context = {
        'top_destinations': Destination.objects.order_by('-rating')[:6],
        'total_destinations': Destination.objects.count(),
        'total_places': Place.objects.count(),
        'total_trips': Trip.objects.count(),
    }
    return render(request, 'home.html', context)


def destinations(request):
    query = request.GET.get('q', '').strip()
    qs = Destination.objects.all().order_by('-rating')
    if query:
        qs = qs.filter(Q(name__icontains=query) | Q(city__icontains=query) |
                       Q(state__icontains=query) | Q(category__icontains=query))
    return render(request, 'destinations.html', {'destinations': qs, 'query': query})


def destination_detail(request, pk):
    destination = get_object_or_404(Destination, pk=pk)
    return render(request, 'destination_detail.html', {
        'destination': destination,
        'places': destination.places.all().order_by('-rating'),
        'hotels': destination.hotels.all().order_by('-rating'),
        'forecast': get_weather_forecast(destination, days=3),
    })


# ---------------- Authentication ----------------

def register_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    form = RegisterForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = form.save()
        login(request, user)
        messages.success(request, 'Welcome to SmartTrip AI, ' + user.username + '!')
        return redirect('dashboard')
    return render(request, 'register.html', {'form': form})


def login_view(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    form = LoginForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user = authenticate(request,
                            username=form.cleaned_data['username'],
                            password=form.cleaned_data['password'])
        if user is not None:
            login(request, user)
            return redirect(request.GET.get('next') or 'dashboard')
        messages.error(request, 'Invalid username or password.')
    return render(request, 'login.html', {'form': form})


def logout_view(request):
    logout(request)
    messages.info(request, 'You have been logged out.')
    return redirect('home')


@login_required
def profile_view(request):
    profile = request.user.profile
    form = UserProfileForm(request.POST or None, request.FILES or None, instance=profile)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Profile updated.')
        return redirect('profile')
    stats = {
        'trips': TripMember.objects.filter(user=request.user).count(),
        'owned': Trip.objects.filter(owner=request.user).count(),
        'expenses': Expense.objects.filter(paid_by=request.user).count(),
        'journal': TripJournal.objects.filter(user=request.user).count(),
    }
    return render(request, 'profile.html', {'form': form, 'stats': stats})


# ---------------- Dashboard & trips ----------------

@login_required
def dashboard(request):
    memberships = (TripMember.objects.filter(user=request.user)
                   .select_related('trip', 'trip__destination')
                   .order_by('-trip__created_at'))
    trips = [m.trip for m in memberships]
    context = {
        'memberships': memberships,
        'owned_count': sum(1 for t in trips if t.owner_id == request.user.id),
        'shared_count': sum(1 for t in trips if t.owner_id != request.user.id),
        'saved_count': SavedTrip.objects.filter(user=request.user).count(),
    }
    return render(request, 'dashboard.html', context)


@login_required
def trip_create(request):
    form = TripForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        trip = form.save(commit=False)
        trip.owner = request.user
        trip.interests = ','.join(form.cleaned_data['interests'])
        trip.save()
        TripMember.objects.create(trip=trip, user=request.user, role='Owner')
        for title, category in DEFAULT_CHECKLIST:
            ChecklistItem.objects.create(trip=trip, title=title, category=category)
        messages.success(request, 'Trip created! This is your trip workspace - everything '
                                  'about this trip lives here.')
        return redirect('trip_detail', pk=trip.pk)
    return render(request, 'create_trip.html', {'form': form})


@login_required
def trip_detail(request, pk):
    trip = _get_trip(request, pk)
    total_spent = _total_spent(trip)
    remaining = trip.total_budget - total_spent
    score, breakdown = compute_trip_score(trip, total_spent)
    forecast = get_weather_forecast(trip.destination, days=3)
    checklist_items = list(trip.checklist_items.all())
    context = {
        'trip': trip, 'active_tab': 'overview',
        'total_spent': total_spent, 'remaining': remaining,
        'score': score, 'breakdown': breakdown,
        'members_count': trip.members.count(),
        'itinerary_count': trip.itinerary_items.count(),
        'open_votes': trip.votes.filter(status='Open').count(),
        'forecast': forecast,
        'recent_journal': trip.journal_entries.all()[:3],
        'checklist_done': sum(1 for i in checklist_items if i.completed),
        'checklist_total': len(checklist_items),
        'is_saved': SavedTrip.objects.filter(user=request.user, trip=trip).exists(),
        'recommendations_count': trip.recommendations.count(),
    }
    return render(request, 'trip_detail.html', context)


@login_required
def trip_edit(request, pk):
    trip = _get_trip(request, pk, owner_only=True)
    form = TripForm(request.POST or None, instance=trip,
                    initial={'interests': trip.interest_list()})
    if request.method == 'POST' and form.is_valid():
        trip = form.save(commit=False)
        trip.interests = ','.join(form.cleaned_data['interests'])
        trip.save()
        messages.success(request, 'Trip updated.')
        return redirect('trip_detail', pk=trip.pk)
    return render(request, 'create_trip.html', {'form': form, 'editing': True, 'trip': trip})


@login_required
@require_POST
def trip_delete(request, pk):
    trip = _get_trip(request, pk, owner_only=True)
    trip.delete()
    messages.info(request, 'Trip deleted.')
    return redirect('dashboard')


@login_required
@require_POST
def trip_save(request, pk):
    trip = _get_trip(request, pk)
    SavedTrip.objects.get_or_create(user=request.user, trip=trip)
    messages.success(request, 'Trip saved to your collection.')
    return redirect('trip_detail', pk=pk)


@login_required
@require_POST
def trip_unsave(request, pk):
    trip = _get_trip(request, pk)
    SavedTrip.objects.filter(user=request.user, trip=trip).delete()
    messages.info(request, 'Trip removed from saved collection.')
    return redirect('trip_detail', pk=pk)


@login_required
def saved_trips(request):
    saved = (SavedTrip.objects.filter(user=request.user)
             .select_related('trip', 'trip__destination').order_by('-saved_at'))
    return render(request, 'saved_trips.html', {'saved': saved})


# ---------------- Itinerary (AI planner) ----------------

@login_required
def itinerary(request, pk):
    trip = _get_trip(request, pk)
    items = trip.itinerary_items.select_related('place').all()
    days = []
    for d in range(1, trip.duration_days + 1):
        days.append({
            'day_number': d,
            'date': trip.start_date + timedelta(days=d - 1),
            'items': [i for i in items if i.day_number == d],
        })
    form = ItineraryItemForm(trip=trip)
    return render(request, 'itinerary.html', {
        'trip': trip, 'active_tab': 'itinerary', 'days': days, 'form': form,
        'is_owner': trip.owner_id == request.user.id,
    })


@login_required
@require_POST
def itinerary_generate(request, pk):
    """AI trip planner pipeline: recommendations -> K-Means day clustering -> TSP ordering."""
    trip = _get_trip(request, pk, owner_only=True)
    forecast = get_weather_forecast(trip.destination, days=trip.duration_days)
    ranked = recommend_places(trip, forecast)
    if not ranked:
        messages.error(request, 'No places are available for this destination yet.')
        return redirect('itinerary', pk=pk)
    per_day = 3
    top = ranked[:trip.duration_days * per_day]
    places = [r[0] for r in top]
    points = [(p.latitude, p.longitude) for p in places]
    clusters = [c for c in kmeans_cluster(points, trip.duration_days) if c]
    trip.itinerary_items.all().delete()
    created = 0
    for day_index, cluster in enumerate(clusters[:trip.duration_days]):
        cluster_points = [points[i] for i in cluster]
        order = tsp_optimize(cluster_points)['optimized_order']
        current = 9.0
        for pos, idx in enumerate(order):
            place = places[cluster[idx]]
            duration = max(place.estimated_visit_time, 0.5)
            if current + duration > 20.0:
                break
            start = dtime(int(current), int((current % 1) * 60))
            end_h = current + duration
            end = dtime(min(int(end_h), 23), int((end_h % 1) * 60))
            ItineraryItem.objects.create(
                trip=trip, day_number=day_index + 1,
                date=trip.start_date + timedelta(days=day_index),
                place=place, start_time=start, end_time=end, order=pos + 1,
                notes='Auto-planned by SmartTrip AI')
            created += 1
            current = end_h + 1.0
    messages.success(request, 'Smart itinerary generated: {0} activities across {1} day(s), '
                              'clustered by location (K-Means) and ordered for minimal travel '
                              '(TSP).'.format(created, min(len(clusters), trip.duration_days)))
    return redirect('itinerary', pk=pk)


@login_required
@require_POST
def itinerary_add(request, pk):
    trip = _get_trip(request, pk, owner_only=True)
    form = ItineraryItemForm(request.POST, trip=trip)
    if form.is_valid():
        item = form.save(commit=False)
        if item.day_number < 1 or item.day_number > trip.duration_days:
            messages.error(request, 'Day number must be between 1 and {0}.'.format(trip.duration_days))
            return redirect('itinerary', pk=pk)
        item.trip = trip
        item.date = trip.start_date + timedelta(days=item.day_number - 1)
        item.order = trip.itinerary_items.filter(day_number=item.day_number).count() + 1
        item.save()
        messages.success(request, 'Activity added to day {0}.'.format(item.day_number))
    else:
        messages.error(request, 'Could not add activity - please check the form values.')
    return redirect('itinerary', pk=pk)


@login_required
@require_POST
def itinerary_delete(request, pk, item_id):
    trip = _get_trip(request, pk, owner_only=True)
    get_object_or_404(ItineraryItem, pk=item_id, trip=trip).delete()
    messages.info(request, 'Activity removed.')
    return redirect('itinerary', pk=pk)


# ---------------- Budget (Fractional Knapsack) ----------------

@login_required
def budget(request, pk):
    trip = _get_trip(request, pk)
    total_spent = _total_spent(trip)
    split = BUDGET_SPLITS.get(trip.travel_style, BUDGET_SPLITS['Balanced'])
    spent_by_cat = {row['category']: row['total'] for row in
                    trip.expenses.values('category').annotate(total=Sum('amount'))}
    allocations = []
    activity_budget = 0.0
    for category, percent in split:
        amount = float(trip.total_budget) * percent / 100.0
        if category == 'Activities':
            activity_budget = amount
        allocations.append({
            'category': category, 'percent': percent,
            'amount': round(amount, 2),
            'spent': float(spent_by_cat.get(category, 0)),
        })
    items = [{'name': p.name, 'category': p.category,
              'cost': float(p.entry_fee) * trip.number_of_people,
              'value': float(p.rating) * 20 + (10 if p.category in trip.interest_list() else 0)}
             for p in trip.destination.places.all() if float(p.entry_fee) > 0]
    knapsack = fractional_knapsack(items, activity_budget) if items else None
    return render(request, 'budget.html', {
        'trip': trip, 'active_tab': 'budget',
        'allocations': allocations, 'total_spent': total_spent,
        'remaining': trip.total_budget - total_spent,
        'per_person': round(float(trip.total_budget) / max(trip.number_of_people, 1), 2),
        'per_day': round(float(trip.total_budget) / max(trip.duration_days, 1), 2),
        'activity_budget': round(activity_budget, 2),
        'knapsack': knapsack, 'rates': get_currency_rates(),
    })


# ---------------- Expenses & settlement ----------------

@login_required
def expenses(request, pk):
    trip = _get_trip(request, pk)
    expense_list = trip.expenses.select_related('paid_by').prefetch_related('participants__user')
    members = trip.members.select_related('user')
    paid_map = {}
    owed_map = {}
    for exp in expense_list:
        paid_map[exp.paid_by.username] = paid_map.get(exp.paid_by.username, 0.0) + float(exp.amount)
        for part in exp.participants.all():
            owed_map[part.user.username] = owed_map.get(part.user.username, 0.0) + float(part.share_amount)
    balances = []
    net_map = {}
    for m in members:
        name = m.user.username
        paid = round(paid_map.get(name, 0.0), 2)
        owed = round(owed_map.get(name, 0.0), 2)
        net = round(paid - owed, 2)
        net_map[name] = net
        balances.append({'user': m.user, 'paid': paid, 'owed': owed, 'net': net})
    settlements = settle_expenses(net_map)
    category_totals = list(trip.expenses.values('category').annotate(total=Sum('amount')))
    return render(request, 'expenses.html', {
        'trip': trip, 'active_tab': 'expenses',
        'expense_list': expense_list, 'form': ExpenseForm(),
        'members': members, 'balances': balances, 'settlements': settlements,
        'category_totals': category_totals, 'total_spent': _total_spent(trip),
    })


@login_required
@require_POST
def expense_add(request, pk):
    trip = _get_trip(request, pk)
    form = ExpenseForm(request.POST)
    participant_ids = request.POST.getlist('participants')
    if form.is_valid():
        expense = form.save(commit=False)
        expense.trip = trip
        expense.paid_by = request.user
        expense.save()
        member_users = [m.user for m in trip.members.select_related('user')]
        if participant_ids:
            selected = [u for u in member_users if str(u.id) in participant_ids]
        else:
            selected = member_users
        if not selected:
            selected = [request.user]
        share = round(float(expense.amount) / len(selected), 2)
        for u in selected:
            ExpenseParticipant.objects.create(expense=expense, user=u, share_amount=share)
        messages.success(request, 'Expense added and split between {0} member(s).'.format(len(selected)))
    else:
        messages.error(request, 'Could not add expense - please check the form values.')
    return redirect('expenses', pk=pk)


@login_required
@require_POST
def expense_delete(request, pk, expense_id):
    trip = _get_trip(request, pk)
    expense = get_object_or_404(Expense, pk=expense_id, trip=trip)
    if expense.paid_by_id != request.user.id and trip.owner_id != request.user.id:
        raise PermissionDenied('Only the payer or the trip owner can delete this expense.')
    expense.delete()
    messages.info(request, 'Expense deleted.')
    return redirect('expenses', pk=pk)


# ---------------- Group ----------------

@login_required
def group(request, pk):
    trip = _get_trip(request, pk)
    return render(request, 'group.html', {
        'trip': trip, 'active_tab': 'group',
        'members': trip.members.select_related('user'),
        'invite_form': InviteForm(),
        'is_owner': trip.owner_id == request.user.id,
    })


@login_required
@require_POST
def member_invite(request, pk):
    trip = _get_trip(request, pk, owner_only=True)
    form = InviteForm(request.POST)
    if form.is_valid():
        identifier = form.cleaned_data['identifier'].strip()
        user = User.objects.filter(Q(username__iexact=identifier) |
                                   Q(email__iexact=identifier)).first()
        if user is None:
            messages.error(request, 'No registered user matches "{0}". Ask them to register first.'.format(identifier))
        elif trip.members.filter(user=user).exists():
            messages.warning(request, user.username + ' is already a member of this trip.')
        else:
            TripMember.objects.create(trip=trip, user=user, role='Member')
            messages.success(request, user.username + ' has been added to the trip.')
    return redirect('group', pk=pk)


@login_required
@require_POST
def member_remove(request, pk, member_id):
    trip = _get_trip(request, pk, owner_only=True)
    member = get_object_or_404(TripMember, pk=member_id, trip=trip)
    if member.role == 'Owner':
        messages.error(request, 'The trip owner cannot be removed.')
    else:
        member.delete()
        messages.info(request, 'Member removed from the trip.')
    return redirect('group', pk=pk)


# ---------------- Voting ----------------

@login_required
def voting(request, pk):
    trip = _get_trip(request, pk)
    votes_data = []
    for vote in trip.votes.prefetch_related('options'):
        total = vote.total_responses()
        options = []
        for option in vote.options.all():
            count = option.response_count()
            options.append({'option': option, 'count': count,
                            'pct': round(count * 100.0 / total, 1) if total else 0})
        my_response = VoteResponse.objects.filter(vote=vote, user=request.user).first()
        votes_data.append({'vote': vote, 'options': options, 'total': total,
                           'my_choice': my_response.option_id if my_response else None})
    return render(request, 'voting.html', {
        'trip': trip, 'active_tab': 'voting', 'votes_data': votes_data,
        'form': VoteForm(), 'is_owner': trip.owner_id == request.user.id,
    })


@login_required
@require_POST
def vote_create(request, pk):
    trip = _get_trip(request, pk, owner_only=True)
    form = VoteForm(request.POST)
    if form.is_valid():
        vote = form.save(commit=False)
        vote.trip = trip
        vote.created_by = request.user
        vote.save()
        for line in form.cleaned_data['options_text']:
            VoteOption.objects.create(vote=vote, option_name=line)
        messages.success(request, 'Poll created - members can vote now.')
    else:
        messages.error(request, 'Could not create poll - provide a title and at least two options.')
    return redirect('voting', pk=pk)


@login_required
@require_POST
def vote_cast(request, pk, vote_id):
    trip = _get_trip(request, pk)
    vote = get_object_or_404(Vote, pk=vote_id, trip=trip)
    if vote.status != 'Open':
        messages.error(request, 'This poll is closed.')
        return redirect('voting', pk=pk)
    option = get_object_or_404(VoteOption, pk=request.POST.get('option_id'), vote=vote)
    VoteResponse.objects.update_or_create(vote=vote, user=request.user,
                                          defaults={'option': option})
    messages.success(request, 'Your vote for "{0}" was recorded.'.format(option.option_name))
    return redirect('voting', pk=pk)


@login_required
@require_POST
def vote_close(request, pk, vote_id):
    trip = _get_trip(request, pk, owner_only=True)
    vote = get_object_or_404(Vote, pk=vote_id, trip=trip)
    vote.status = 'Closed'
    vote.save()
    messages.info(request, 'Poll closed.')
    return redirect('voting', pk=pk)


# ---------------- Recommendations ----------------

@login_required
def recommendations_view(request, pk):
    trip = _get_trip(request, pk)
    if request.method == 'POST':
        forecast = get_weather_forecast(trip.destination, days=trip.duration_days)
        ranked = recommend_places(trip, forecast, limit=10)
        trip.recommendations.all().delete()
        for place, score, reason in ranked:
            Recommendation.objects.create(trip=trip, place=place, score=score, reason=reason)
        messages.success(request, '{0} personalised recommendations generated using '
                                  'content-based filtering, weighted scoring and weather '
                                  'suitability.'.format(len(ranked)))
        return redirect('recommendations', pk=pk)
    return render(request, 'recommendations.html', {
        'trip': trip, 'active_tab': 'recommendations',
        'recs': trip.recommendations.select_related('place'),
    })


# ---------------- Weather ----------------

@login_required
def weather(request, pk):
    trip = _get_trip(request, pk)
    forecast = get_weather_forecast(trip.destination, days=7)
    for day in forecast:
        day['outdoor_score'] = weather_suitability(day['condition'], day['temp_max'], True)
        day['indoor_score'] = weather_suitability(day['condition'], day['temp_max'], False)
        if day['outdoor_score'] >= 70:
            day['advice'] = 'Great day for outdoor sightseeing.'
        elif day['outdoor_score'] >= 45:
            day['advice'] = 'Outdoor plans are possible - keep a backup.'
        else:
            day['advice'] = 'Prefer indoor activities (museums, food, shopping).'
    forecast_by_date = {d['date']: d for d in forecast}
    affected_items = []
    for item in trip.itinerary_items.select_related('place'):
        day = forecast_by_date.get(item.date)
        if day and item.place.is_outdoor and day['outdoor_score'] < 45:
            affected_items.append({'item': item, 'day': day})
    return render(request, 'weather.html', {
        'trip': trip, 'active_tab': 'weather', 'forecast': forecast,
        'affected_items': affected_items,
    })


@login_required
@require_POST
def weather_replan(request, pk):
    """Smart replanning: swap outdoor activities on bad-weather days for indoor ones."""
    trip = _get_trip(request, pk, owner_only=True)
    forecast = {d['date']: d for d in get_weather_forecast(trip.destination, days=7)}
    scheduled_ids = set(trip.itinerary_items.values_list('place_id', flat=True))
    indoor_pool = [p for p in trip.destination.places.all().order_by('-rating')
                   if not p.is_outdoor and p.id not in scheduled_ids]
    changes = []
    for item in trip.itinerary_items.select_related('place'):
        day = forecast.get(item.date)
        if not day or not item.place.is_outdoor:
            continue
        if weather_suitability(day['condition'], day['temp_max'], True) < 45 and indoor_pool:
            replacement = indoor_pool.pop(0)
            changes.append('Day {0}: {1} replaced with {2} ({3} expected)'.format(
                item.day_number, item.place.name, replacement.name, day['condition']))
            item.place = replacement
            item.notes = 'Swapped by weather-aware replanning ({0} expected)'.format(day['condition'])
            item.save()
    if changes:
        messages.success(request, 'Replanned for weather: ' + ' | '.join(changes))
    else:
        messages.info(request, 'No changes needed - your itinerary already suits the forecast.')
    return redirect('weather', pk=pk)


# ---------------- Map & routes (TSP + Dijkstra) ----------------

@login_required
def map_view(request, pk):
    trip = _get_trip(request, pk)
    places = list(trip.destination.places.all())
    places_payload = [{'id': p.id, 'name': p.name, 'lat': p.latitude, 'lng': p.longitude,
                       'category': p.category, 'rating': p.rating} for p in places]
    hotels_payload = [{'name': h.name, 'lat': h.latitude, 'lng': h.longitude,
                       'price': float(h.price_per_night)} for h in trip.destination.hotels.all()]
    tsp_result = None
    tsp_coords = []
    dijkstra_result = None
    dijkstra_coords = []
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'tsp':
            ids = [int(x) for x in request.POST.getlist('place_ids')]
            selected = [p for p in places if p.id in ids]
            if len(selected) >= 2:
                pts = [(p.latitude, p.longitude) for p in selected]
                res = tsp_optimize(pts)
                tsp_result = {
                    'original': [selected[i].name for i in res['original_order']],
                    'optimized': [selected[i].name for i in res['optimized_order']],
                    'original_distance': res['original_distance'],
                    'optimized_distance': res['optimized_distance'],
                    'distance_saved': res['distance_saved'],
                }
                tsp_coords = [[selected[i].latitude, selected[i].longitude]
                              for i in res['optimized_order']]
            else:
                messages.error(request, 'Select at least two places to optimize a route.')
        elif action == 'dijkstra':
            try:
                start_id = int(request.POST.get('start_id'))
                end_id = int(request.POST.get('end_id'))
            except (TypeError, ValueError):
                start_id = end_id = None
            id_index = {p.id: i for i, p in enumerate(places)}
            if start_id in id_index and end_id in id_index and start_id != end_id:
                pts = [(p.latitude, p.longitude) for p in places]
                res = dijkstra_shortest_path(pts, id_index[start_id], id_index[end_id])
                if res['path']:
                    dijkstra_result = {
                        'path': [places[i].name for i in res['path']],
                        'distance': res['distance'],
                    }
                    dijkstra_coords = [[places[i].latitude, places[i].longitude]
                                       for i in res['path']]
                else:
                    messages.error(request, 'No path found between those places.')
            else:
                messages.error(request, 'Pick two different places for the shortest path.')
    return render(request, 'map.html', {
        'trip': trip, 'active_tab': 'map', 'places': places,
        'places_json': json.dumps(places_payload),
        'hotels_json': json.dumps(hotels_payload),
        'center_lat': trip.destination.latitude, 'center_lng': trip.destination.longitude,
        'tsp_result': tsp_result, 'tsp_json': json.dumps(tsp_coords),
        'dijkstra_result': dijkstra_result, 'dijkstra_json': json.dumps(dijkstra_coords),
    })


# ---------------- Assistant ----------------

@login_required
def assistant(request, pk):
    trip = _get_trip(request, pk)
    session_key = 'assistant_chat_' + str(trip.pk)
    chat = request.session.get(session_key, [])
    if request.method == 'POST':
        if request.POST.get('action') == 'clear':
            chat = []
        else:
            message = request.POST.get('message', '').strip()
            if message:
                total_spent = _total_spent(trip)
                reply = assistant_reply(trip, message, total_spent,
                                        trip.total_budget - total_spent)
                chat.append({'role': 'user', 'text': message})
                chat.append({'role': 'assistant', 'text': reply})
                chat = chat[-30:]
        request.session[session_key] = chat
        return redirect('assistant', pk=pk)
    return render(request, 'assistant.html', {'trip': trip, 'active_tab': 'assistant',
                                              'chat': chat})


# ---------------- Analytics ----------------

@login_required
def analytics(request, pk):
    trip = _get_trip(request, pk)
    total_spent = _total_spent(trip)
    score, breakdown = compute_trip_score(trip, total_spent)
    cat_rows = list(trip.expenses.values('category').annotate(total=Sum('amount')))
    member_rows = list(trip.expenses.values('paid_by__username').annotate(total=Sum('amount')))
    daily_rows = list(trip.expenses.values('date').annotate(total=Sum('amount')).order_by('date'))
    checklist_items = list(trip.checklist_items.all())
    context = {
        'trip': trip, 'active_tab': 'analytics',
        'score': score, 'breakdown': breakdown,
        'total_spent': total_spent, 'remaining': trip.total_budget - total_spent,
        'cat_labels': json.dumps([r['category'] for r in cat_rows]),
        'cat_data': json.dumps([float(r['total']) for r in cat_rows]),
        'member_labels': json.dumps([r['paid_by__username'] for r in member_rows]),
        'member_data': json.dumps([float(r['total']) for r in member_rows]),
        'daily_labels': json.dumps([r['date'].strftime('%d %b') for r in daily_rows]),
        'daily_data': json.dumps([float(r['total']) for r in daily_rows]),
        'stats': {
            'activities': trip.itinerary_items.count(),
            'members': trip.members.count(),
            'expenses': trip.expenses.count(),
            'votes': trip.votes.count(),
            'journal': trip.journal_entries.count(),
            'checklist_done': sum(1 for i in checklist_items if i.completed),
            'checklist_total': len(checklist_items),
        },
    }
    return render(request, 'analytics.html', context)


# ---------------- Checklist ----------------

@login_required
def checklist(request, pk):
    trip = _get_trip(request, pk)
    items = list(trip.checklist_items.all())
    groups = {}
    for item in items:
        groups.setdefault(item.category, []).append(item)
    done = sum(1 for i in items if i.completed)
    total = len(items)
    return render(request, 'checklist.html', {
        'trip': trip, 'active_tab': 'checklist',
        'groups': [{'category': c, 'items': lst} for c, lst in groups.items()],
        'form': ChecklistItemForm(), 'done': done, 'total': total,
        'pct': round(done * 100.0 / total, 0) if total else 0,
    })


@login_required
@require_POST
def checklist_add(request, pk):
    trip = _get_trip(request, pk)
    form = ChecklistItemForm(request.POST)
    if form.is_valid():
        item = form.save(commit=False)
        item.trip = trip
        item.save()
        messages.success(request, 'Checklist item added.')
    return redirect('checklist', pk=pk)


@login_required
@require_POST
def checklist_toggle(request, pk, item_id):
    trip = _get_trip(request, pk)
    item = get_object_or_404(ChecklistItem, pk=item_id, trip=trip)
    item.completed = not item.completed
    item.save()
    return redirect('checklist', pk=pk)


@login_required
@require_POST
def checklist_delete(request, pk, item_id):
    trip = _get_trip(request, pk)
    get_object_or_404(ChecklistItem, pk=item_id, trip=trip).delete()
    return redirect('checklist', pk=pk)


# ---------------- Journal ----------------

@login_required
def journal(request, pk):
    trip = _get_trip(request, pk)
    return render(request, 'journal.html', {
        'trip': trip, 'active_tab': 'journal',
        'entries': trip.journal_entries.select_related('user'),
        'form': JournalForm(),
    })


@login_required
@require_POST
def journal_add(request, pk):
    trip = _get_trip(request, pk)
    form = JournalForm(request.POST, request.FILES)
    if form.is_valid():
        entry = form.save(commit=False)
        entry.trip = trip
        entry.user = request.user
        entry.save()
        messages.success(request, 'Journal entry added.')
    else:
        messages.error(request, 'Could not add journal entry.')
    return redirect('journal', pk=pk)


@login_required
@require_POST
def journal_delete(request, pk, entry_id):
    trip = _get_trip(request, pk)
    entry = get_object_or_404(TripJournal, pk=entry_id, trip=trip)
    if entry.user_id != request.user.id and trip.owner_id != request.user.id:
        raise PermissionDenied('Only the author or trip owner can delete this entry.')
    entry.delete()
    return redirect('journal', pk=pk)
