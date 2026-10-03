from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render

from .forms import (
    ExpenseForm,
    ProfileForm,
    RegisterForm,
    ScenarioForm,
    TripForm,
)
from .models import (
    Attraction,
    BudgetExpense,
    Destination,
    GroupTrip,
    ItineraryItem,
    Profile,
    RecommendationFeedback,
    SavedTrip,
    Trip,
    TripReplanLog,
)
from .services.feasibility import check_feasibility, what_if
from .services.learning import preference_summary
from .services.optimizer import optimize_trip, itinerary_quality
from .services.poi import cluster_summary
from .services.recommendation import recommendation_score
from .services.sustainability import trip_sustainability
from .services.weather import alternative_for, weather_context


def _feedback_ids(user):
    return set(
        RecommendationFeedback.objects.filter(
            user=user,
            action="like",
        ).values_list(
            "attraction_id",
            flat=True,
        )
    )


def _disliked_ids(user):
    return set(
        RecommendationFeedback.objects.filter(
            user=user,
            action="dislike",
        ).values_list(
            "attraction_id",
            flat=True,
        )
    )


def _build_itinerary(trip, user):
    attractions = list(
        trip.destination.attractions.all()
    )

    likes = _feedback_ids(user)
    trip._disliked_attraction_ids = _disliked_ids(user)

    plan = optimize_trip(
        trip,
        attractions,
        likes,
    )

    trip.items.all().delete()

    used_alternative_ids = set()

    for item in plan:
        alternative = None

        if trip.weather_adaptive:
            alternative = alternative_for(
                attractions=attractions,
                day_number=item["day"],
                exclude_ids=used_alternative_ids,
                current_attraction_id=item["attraction"].id,
            )

            if alternative:
                used_alternative_ids.add(alternative.id)

        ItineraryItem.objects.create(
            trip=trip,
            day_number=item["day"],
            attraction=item["attraction"],
            start_time=item["start"],
            score=item["score"],
            reason=item["reason"],
            weather_alternative=alternative,
        )

    return len(plan)


def home(request):
    featured = Destination.objects.all()[:6]

    return render(
        request,
        "travel/index.html",
        {"featured": featured},
    )


def register_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    form = RegisterForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                user = form.save()
                Profile.objects.get_or_create(user=user)

            login(request, user)
            messages.success(
                request,
                f"Welcome to SmartTrip, {user.username}!",
            )
            return redirect("dashboard")

        except IntegrityError:
            form.add_error(
                "username",
                "This username is already registered.",
            )

    return render(
        request,
        "travel/register.html",
        {"form": form},
    )


def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")

        if not username or not password:
            messages.error(
                request,
                "Please enter both username and password.",
            )
        else:
            user = authenticate(
                request,
                username=username,
                password=password,
            )

            if user is not None:
                login(request, user)
                messages.success(
                    request,
                    f"Welcome back, {user.username}!",
                )
                return redirect("dashboard")

            messages.error(
                request,
                "Invalid username or password.",
            )

    return render(
        request,
        "travel/login.html",
    )


def logout_view(request):
    logout(request)
    messages.success(
        request,
        "You have been logged out successfully.",
    )
    return redirect("home")


@login_required
def dashboard(request):
    trips = (
        request.user.trips
        .select_related("destination")
        .order_by("-created_at")[:6]
    )

    return render(
        request,
        "travel/dashboard.html",
        {
            "trips": trips,
            "trip_count": request.user.trips.count(),
            "saved_count": request.user.saved_trips.count(),
            "learned": preference_summary(request.user),
        },
    )


@login_required
def profile(request):
    profile_obj, _ = Profile.objects.get_or_create(
        user=request.user
    )

    form = ProfileForm(
        request.POST or None,
        instance=profile_obj,
    )

    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(
            request,
            "Your travel preferences have been updated.",
        )
        return redirect("profile")

    return render(
        request,
        "travel/profile.html",
        {
            "form": form,
            "profile": profile_obj,
        },
    )


def destinations(request):
    query = request.GET.get("q", "").strip()
    interest = request.GET.get("interest", "").strip().lower()

    items = Destination.objects.all()

    if query:
        items = items.filter(
            Q(name__icontains=query)
            | Q(state__icontains=query)
        )

    if interest:
        items = items.filter(
            best_for__icontains=interest
        )

    return render(
        request,
        "travel/destinations.html",
        {
            "destinations": items.distinct(),
            "q": query,
            "interest": interest,
        },
    )


def destination_detail(request, pk):
    destination = get_object_or_404(
        Destination,
        pk=pk,
    )

    attractions = sorted(
        destination.attractions.all(),
        key=lambda attraction: (
            -attraction.hidden_gem_score,
            -attraction.sustainability_score,
        ),
    )

    return render(
        request,
        "travel/destination_detail.html",
        {
            "destination": destination,
            "attractions": attractions,
            "clusters": cluster_summary(attractions),
        },
    )


@login_required
def trip_planner(request):
    form = TripForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        trip = form.save(commit=False)
        trip.user = request.user
        trip.save()

        created_count = _build_itinerary(
            trip,
            request.user,
        )

        if created_count:
            messages.success(
                request,
                f"Personalized itinerary generated with "
                f"{created_count} activity item(s).",
            )
            return redirect(
                "trip_detail",
                pk=trip.pk,
            )

        messages.error(
            request,
            "SmartTrip could not generate an itinerary for this destination.",
        )
        trip.delete()

    return render(
        request,
        "travel/trip_planner.html",
        {"form": form},
    )


@login_required
def trip_detail(request, pk):
    trip = get_object_or_404(
        Trip.objects.select_related("destination"),
        pk=pk,
        user=request.user,
    )

    groups = []

    for day in range(1, trip.days + 1):
        items = (
            trip.items
            .filter(day_number=day)
            .select_related(
                "attraction",
                "weather_alternative",
            )
        )

        groups.append(
            {
                "number": day,
                "items": items,
                "weather": weather_context(day),
            }
        )

    feasibility = check_feasibility(trip)
    quality = itinerary_quality(trip)
    sustainability = trip_sustainability(trip)

    return render(
        request,
        "travel/trip_detail.html",
        {
            "trip": trip,
            "groups": groups,
            "quality": quality,
            "sustainability": sustainability,
            "feasibility": feasibility,
            "saved": SavedTrip.objects.filter(
                user=request.user,
                trip=trip,
            ).exists(),
        },
    )


@login_required
def save_trip(request, pk):
    trip = get_object_or_404(
        Trip,
        pk=pk,
        user=request.user,
    )

    SavedTrip.objects.get_or_create(
        user=request.user,
        trip=trip,
    )

    messages.success(
        request,
        "Trip saved successfully.",
    )

    return redirect(
        "trip_detail",
        pk=pk,
    )


@login_required
def remove_saved_trip(request, pk):
    trip = get_object_or_404(
        Trip,
        pk=pk,
        user=request.user,
    )

    saved_trip = SavedTrip.objects.filter(
        user=request.user,
        trip=trip,
    ).first()

    if saved_trip:
        saved_trip.delete()
        messages.success(
            request,
            "Trip removed from your saved trips.",
        )
    else:
        messages.info(
            request,
            "This trip is not in your saved trips.",
        )

    return redirect("saved_trips")


@login_required
def feedback(request, pk, item_id, action):
    trip = get_object_or_404(
        Trip,
        pk=pk,
        user=request.user,
    )

    item = get_object_or_404(
        ItineraryItem,
        pk=item_id,
        trip=trip,
    )

    if action not in {"like", "dislike"}:
        messages.error(
            request,
            "Invalid feedback action.",
        )
        return redirect(
            "trip_detail",
            pk=trip.pk,
        )

    RecommendationFeedback.objects.create(
        user=request.user,
        trip=trip,
        attraction=item.attraction,
        action=action,
    )

    messages.success(
        request,
        f"Feedback recorded: {action}. Future recommendations will learn from it.",
    )

    return redirect(
        "trip_detail",
        pk=trip.pk,
    )


@login_required
def budget(request, pk):
    trip = get_object_or_404(
        Trip,
        pk=pk,
        user=request.user,
    )

    form = ExpenseForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        expense = form.save(commit=False)
        expense.trip = trip
        expense.save()

        messages.success(
            request,
            "Expense added successfully.",
        )

        return redirect(
            "budget",
            pk=pk,
        )

    total = (
        trip.expenses.aggregate(
            total=Sum("amount")
        )["total"]
        or 0
    )

    return render(
        request,
        "travel/budget.html",
        {
            "trip": trip,
            "form": form,
            "expenses": trip.expenses.order_by("-created_at"),
            "total": total,
            "remaining": max(0, trip.budget - total),
        },
    )


@login_required
def saved_trips(request):
    saved = (
        request.user.saved_trips
        .select_related(
            "trip",
            "trip__destination",
        )
    )

    return render(
        request,
        "travel/saved_trips.html",
        {"saved": saved},
    )


@login_required
def recommendations(request):
    destination_id = request.GET.get("destination")

    destination = (
        get_object_or_404(
            Destination,
            pk=destination_id,
        )
        if destination_id
        else Destination.objects.first()
    )

    if destination is None:
        messages.error(
            request,
            "No destinations are available yet.",
        )
        return redirect("destinations")

    interest = request.GET.get(
        "interest",
        "culture",
    ).strip()

    class RecommendationProfile:
        pass

    profile = RecommendationProfile()
    profile.interest = interest
    profile.sustainability_priority = 4
    profile.include_hidden_gems = True

    ranked = sorted(
        destination.attractions.all(),
        key=lambda attraction: recommendation_score(
            attraction,
            profile,
        ),
        reverse=True,
    )

    recommendations_data = [
        (
            attraction,
            recommendation_score(
                attraction,
                profile,
            ),
        )
        for attraction in ranked
    ]

    return render(
        request,
        "travel/recommendations.html",
        {
            "destination": destination,
            "recommendations": recommendations_data,
            "interest": interest,
        },
    )


@login_required
def what_if_view(request, pk):
    trip = get_object_or_404(
        Trip,
        pk=pk,
        user=request.user,
    )

    form = ScenarioForm(request.POST or None)
    result = None

    if request.method == "POST" and form.is_valid():
        scenario = form.save(commit=False)
        scenario.trip = trip

        result = what_if(
            trip,
            scenario.budget_change,
            scenario.extra_days,
        )

        scenario.result_summary = (
            f"Budget ₹{result['budget']}, "
            f"{result['days']} days, "
            f"estimated ₹{result['estimated']}, "
            f"feasible={result['feasible']}"
        )
        scenario.save()

        messages.success(
            request,
            "What-if scenario calculated successfully.",
        )

    return render(
        request,
        "travel/what_if.html",
        {
            "trip": trip,
            "form": form,
            "result": result,
        },
    )


@login_required
def replan(request, pk):
    trip = get_object_or_404(
        Trip,
        pk=pk,
        user=request.user,
    )

    trigger = (
        request.POST.get(
            "trigger",
            "Weather change",
        ).strip()
        if request.method == "POST"
        else "Weather change"
    ) or "Weather change"

    attractions = list(
        trip.destination.attractions.all()
    )

    if not attractions:
        messages.error(
            request,
            "No attractions are available for this destination.",
        )
        return redirect(
            "trip_detail",
            pk=trip.pk,
        )

    likes = _feedback_ids(request.user)
    trip._disliked_attraction_ids = _disliked_ids(request.user)

    new_plan = optimize_trip(
        trip,
        attractions,
        likes,
    )

    if not new_plan:
        messages.error(
            request,
            "SmartTrip could not generate a new itinerary.",
        )
        return redirect(
            "trip_detail",
            pk=trip.pk,
        )

    trip.items.all().delete()

    used_alternative_ids = set()
    created_count = 0

    for plan_item in new_plan:
        attraction = plan_item["attraction"]
        alternative = None

        if trip.weather_adaptive:
            alternative = alternative_for(
                attractions=attractions,
                day_number=plan_item["day"],
                exclude_ids=used_alternative_ids,
                current_attraction_id=attraction.id,
            )

            if alternative:
                used_alternative_ids.add(alternative.id)

        weather = weather_context(plan_item["day"])

        reason = plan_item["reason"]

        if trip.weather_adaptive and alternative:
            reason = (
                f"{reason} Weather-aware planning prepared "
                f"{weather['condition'].lower()} alternatives."
            )

        ItineraryItem.objects.create(
            trip=trip,
            day_number=plan_item["day"],
            attraction=attraction,
            start_time=plan_item["start"],
            score=plan_item["score"],
            reason=reason,
            weather_alternative=alternative,
        )

        created_count += 1

    TripReplanLog.objects.create(
        trip=trip,
        trigger=trigger,
        action=(
            f"Regenerated itinerary with "
            f"{created_count} activity item(s)."
        ),
    )

    messages.success(
        request,
        f"SmartTrip regenerated your itinerary with {created_count} activity item(s).",
    )

    return redirect(
        "trip_detail",
        pk=trip.pk,
    )


@login_required
def group_trip(request, pk):
    trip = get_object_or_404(
        Trip,
        pk=pk,
        user=request.user,
    )

    group, _ = GroupTrip.objects.get_or_create(
        trip=trip,
        defaults={
            "owner": request.user,
            "invite_code": f"ST{trip.id}{request.user.id}",
        },
    )

    if request.method == "POST":
        username = request.POST.get(
            "username",
            "",
        ).strip()

        if not username:
            messages.error(
                request,
                "Please enter a username.",
            )
            return redirect(
                "group",
                pk=pk,
            )

        member = User.objects.filter(
            username=username
        ).first()

        if member is None:
            messages.error(
                request,
                "User not found.",
            )
        elif member == request.user:
            messages.error(
                request,
                "You are already the owner of this group trip.",
            )
        else:
            group.members.add(member)
            messages.success(
                request,
                f"{username} added to the group.",
            )

        return redirect(
            "group",
            pk=pk,
        )

    return render(
        request,
        "travel/group.html",
        {
            "trip": trip,
            "group": group,
        },
    )


@login_required
def assistant(request, pk=None):
    trip = None

    if pk is not None:
        trip = get_object_or_404(
            Trip,
            pk=pk,
            user=request.user,
        )

    answer = None

    if request.method == "POST":
        question = request.POST.get(
            "question",
            "",
        ).strip().lower()

        if not question:
            messages.error(
                request,
                "Please enter a question.",
            )
        elif "weather" in question:
            answer = (
                "SmartTrip uses the weather-aware planning layer "
                "to prepare suitable alternatives for each day."
            )
        elif "budget" in question:
            answer = (
                "Open Budget from your trip to record expenses "
                "and view total spending and remaining budget."
            )
        elif "recommend" in question or "suggest" in question:
            answer = (
                "Recommendations combine interest matching, "
                "sustainability, hidden-gem potential, crowd pressure "
                "and feedback from previous trips."
            )
        elif "why" in question:
            answer = (
                "Each itinerary item stores an explanation showing "
                "the recommendation factors used for its selection."
            )
        elif "what if" in question:
            answer = (
                "Open What-if Planning to test changes to your "
                "budget or trip duration before changing the main trip."
            )
        elif "group" in question:
            answer = (
                "Use Group Planning to add registered users "
                "to a shared trip."
            )
        elif "plan" in question or "itinerary" in question:
            answer = (
                "Trip Planner uses your destination, duration, budget, "
                "interest, pace and preferences to generate an itinerary."
            )
        elif (
            "destination" in question
            or "place" in question
            or "visit" in question
        ):
            answer = (
                "Open Destinations to explore available destinations "
                "and their attractions."
            )
        else:
            answer = (
                "Try asking about recommendations, budget, weather, "
                "itinerary planning, what-if planning, group trips, "
                "destinations or why an attraction was selected."
            )

    return render(
        request,
        "travel/assistant.html",
        {
            "answer": answer,
            "trip": trip,
        },
    )


@login_required
def delete_trip(request, pk):
    trip = get_object_or_404(
        Trip,
        pk=pk,
        user=request.user,
    )

    trip.delete()

    messages.success(
        request,
        "Trip deleted successfully.",
    )

    return redirect("dashboard")
