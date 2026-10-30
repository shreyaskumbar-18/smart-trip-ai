from collections import Counter, defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal
import secrets

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Avg, Count, Q, Sum
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST, require_http_methods

from .forms import (
    BudgetAllocationForm,
    ExpenseForm,
    ProfileForm,
    RegisterForm,
    ReviewForm,
    ScenarioForm,
    TripForm,
)

from .models import (
    Attraction,
    BudgetExpense,
    Destination,
    GroupTrip,
    ItineraryItem,
    OTPVerification,
    Profile,
    RecommendationFeedback,
    Review,
    SavedTrip,
    Trip,
    TripReplanLog,
    UserPreference,
)

from .services.feasibility import check_feasibility, what_if
from .services.learning import (
    get_preferences,
    preference_summary,
    update_preference_from_feedback,
    aggregate_group_preferences,
)
from .services.optimizer import optimize_trip, itinerary_quality, itinerary_comparison_breakdown
from .services.poi import cluster_summary
from .services.recommendation import recommendation_score, recommendation_score_breakdown, explain
from .services.sustainability import trip_sustainability
from .services.weather import alternative_for, weather_context
from .services.ai import assistant_reply, interpret_trip_request
from .services.repair import repair_itinerary
from .services.otp import issue_otp, verify_otp, OTPRequestThrottled
from .services.pdf import trip_pdf
from .services.nsga2 import optimize_pareto
from .services.knapsack import select_attractions_knapsack
from .services.route_algorithms import haversine_km, plan_geographic_path
from .services.copilot import (
    generate_copilot_alternatives,
    refine_itinerary_with_prompt,
)


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def _map_coordinates(attraction):
    """Return validated coordinates for an attraction, or None."""
    try:
        latitude = float(attraction.latitude)
        longitude = float(attraction.longitude)
    except (TypeError, ValueError):
        return None

    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        return None
    return {"latitude": latitude, "longitude": longitude}


def _map_configuration():
    return {
        "tile_url": settings.SMARTTRIP_MAP_TILE_URL,
        "tile_attribution": settings.SMARTTRIP_MAP_TILE_ATTRIBUTION,
        "routing_url": settings.SMARTTRIP_OSRM_ROUTING_URL,
    }

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

    likes = (
        trip._group_feedback_ids
        if hasattr(trip, "_group_feedback_ids")
        else _feedback_ids(user)
    )

    if not hasattr(trip, "_disliked_attraction_ids"):
        trip._disliked_attraction_ids = _disliked_ids(user)

    plan = optimize_trip(
        trip,
        attractions,
        likes,
    )

    trip.items.all().delete()

    used = set()

    for item in plan:

        alternative = None

        if trip.weather_adaptive:

            alternative = alternative_for(
                attractions,
                item["day"],
                used,
                item["attraction"].id,
            )

            if alternative:
                used.add(
                    alternative.id
                )

        ItineraryItem.objects.create(
            trip=trip,
            day_number=item["day"],
            attraction=item["attraction"],
            start_time=item["start"],
            end_time=item.get("end"),
            score=item["score"],
            reason=item["reason"],
            weather_alternative=alternative,
        )

    return len(plan)


# ============================================================
# HOME
# ============================================================

def home(request):

    featured = Destination.objects.all()[:6]

    popular = (
        Destination.objects
        .annotate(
            review_count=Count("reviews")
        )
        .order_by(
            "-rating",
            "-review_count",
        )
    )

    return render(
        request,
        "travel/index.html",
        {
            "featured": featured,
            "popular": popular,
            "destination_count": Destination.objects.count(),
        },
    )


# ============================================================
# REGISTRATION
# ============================================================

def register_view(request):

    if request.user.is_authenticated:
        return redirect("dashboard")

    form = RegisterForm(
        request.POST or None
    )

    if request.method == "POST" and form.is_valid():

        try:

            with transaction.atomic():

                user = form.save(
                    commit=False
                )

                user.is_active = False

                user.save()

                Profile.objects.create(
                    user=user,
                    email_verified=False,
                )

                UserPreference.objects.create(
                    user=user
                )

            request.session["pending_user_id"] = user.pk
            try:
                issue_otp(user, "register")
                messages.success(request, "Verification code sent to your email.")
            except OTPRequestThrottled as e:
                messages.warning(request, str(e))
            except Exception:
                messages.warning(request, "Registration successful. Please check your verification code.")

            return redirect("verify_otp")

        except IntegrityError:

            form.add_error(
                "username",
                "This username is already registered.",
            )

    return render(
        request,
        "travel/register.html",
        {
            "form": form,
        },
    )


# ============================================================
# VERIFY REGISTRATION OTP
# ============================================================

def verify_otp_view(request):

    user_id = request.session.get(
        "pending_user_id"
    )

    user = (
        get_object_or_404(
            User,
            pk=user_id,
        )
        if user_id
        else None
    )

    if not user:
        return redirect(
            "register"
        )

    if request.method == "POST":

        otp = request.POST.get(
            "otp",
            "",
        ).strip()

        ok, msg = verify_otp(
            user,
            "register",
            otp,
        )

        if ok:

            user.is_active = True

            user.save(
                update_fields=[
                    "is_active"
                ]
            )

            profile, _ = (
                Profile.objects.get_or_create(
                    user=user
                )
            )

            profile.email_verified = True

            profile.save(
                update_fields=[
                    "email_verified"
                ]
            )

            UserPreference.objects.get_or_create(
                user=user
            )

            login(
                request,
                user,
            )

            request.session.pop(
                "pending_user_id",
                None,
            )

            messages.success(
                request,
                "Email verified. Welcome to SmartTrip AI.",
            )

            return redirect(
                "dashboard"
            )

        messages.error(
            request,
            msg,
        )

    return render(
        request,
        "travel/verify_otp.html",
        {
            "purpose": "registration",
            "email": user.email,
        },
    )


# ============================================================
# RESEND REGISTRATION OTP
# ============================================================

@require_POST
def resend_otp_view(request):

    user_id = request.session.get(
        "pending_user_id"
    )

    user = (
        get_object_or_404(
            User,
            pk=user_id,
        )
        if user_id
        else None
    )

    if not user:
        return redirect(
            "register"
        )

    try:
        issue_otp(user, "register")
        messages.success(request, "A new OTP has been sent.")
    except OTPRequestThrottled as e:
        messages.warning(request, str(e))
    except Exception:
        messages.error(request, "Could not resend verification email right now.")

    return redirect("verify_otp")


# ============================================================
# NORMAL LOGIN
# ============================================================

def login_view(request):

    if request.user.is_authenticated:
        return redirect(
            "dashboard"
        )

    if request.method == "POST":

        username = request.POST.get(
            "username",
            "",
        ).strip()

        password = request.POST.get(
            "password",
            "",
        )

        user = authenticate(
            request,
            username=username,
            password=password,
        )

        if user is not None:

            profile, _ = (
                Profile.objects.get_or_create(
                    user=user
                )
            )

            if not profile.email_verified:
                request.session["pending_user_id"] = user.pk
                try:
                    issue_otp(user, "register")
                    messages.info(request, "Please verify your email before logging in. A code has been sent.")
                except OTPRequestThrottled as e:
                    messages.warning(request, f"Please verify your email. {e}")
                except Exception:
                    messages.info(request, "Please verify your email before logging in.")

                return redirect("verify_otp")

            login(
                request,
                user,
            )

            messages.success(
                request,
                f"Welcome back, {user.username}!",
            )

            return redirect(
                "dashboard"
            )

        messages.error(
            request,
            "Invalid username or password.",
        )

    return render(
        request,
        "travel/login.html",
    )


# ============================================================
# PASSWORDLESS OTP LOGIN
# ============================================================

def request_otp_login(request):

    if request.method == "POST":

        email = request.POST.get(
            "email",
            "",
        ).strip().lower()

        user = (
            User.objects
            .filter(
                email__iexact=email,
                is_active=True,
            )
            .first()
        )

        if user:

            profile, _ = (
                Profile.objects.get_or_create(
                    user=user
                )
            )

            if not profile.email_verified:

                messages.error(
                    request,
                    "Please verify your email first.",
                )

                return redirect(
                    "login"
                )

            request.session["otp_login_user_id"] = user.pk
            try:
                issue_otp(user, "login")
                messages.info(request, "If this account is eligible, a sign-in code has been sent to its email address.")
            except OTPRequestThrottled as e:
                messages.warning(request, str(e))
            except Exception as e:
                messages.error(request, "Unable to deliver OTP email right now. Please try again.")
                return redirect("otp_login")

            return redirect("otp_login_verify")

        messages.info(request, "If this account is eligible, a sign-in code has been sent to its email address.")

    return render(
        request,
        "travel/otp_login.html",
    )


# ============================================================
# VERIFY OTP LOGIN
# ============================================================

def otp_login_verify(request):

    user_id = request.session.get(
        "otp_login_user_id"
    )

    user = (
        get_object_or_404(
            User,
            pk=user_id,
        )
        if user_id
        else None
    )

    if not user:
        return redirect(
            "otp_login"
        )

    if request.method == "POST":

        otp = request.POST.get(
            "otp",
            "",
        ).strip()

        ok, msg = verify_otp(
            user,
            "login",
            otp,
        )

        if ok:

            login(
                request,
                user,
            )

            request.session.pop(
                "otp_login_user_id",
                None,
            )

            messages.success(
                request,
                "OTP login successful.",
            )

            return redirect(
                "dashboard"
            )

        messages.error(
            request,
            msg,
        )

    return render(
        request,
        "travel/verify_otp.html",
        {
            "purpose": "passwordless login",
            "email": user.email,
        },
    )


# ============================================================
# FORGOT PASSWORD
# ============================================================

PASSWORD_RESET_SESSION_KEYS = (
    "reset_user_id",
    "reset_otp_id",
    "reset_verified_user_id",
    "reset_verified_otp_id",
    "reset_verified_at",
    # Remove state written by the pre-binding reset flow as well.
    "reset_verified",
)


def _clear_password_reset_session(request):
    for key in PASSWORD_RESET_SESSION_KEYS:
        request.session.pop(key, None)


def _bind_password_reset_otp(request, user, otp_record):
    request.session["reset_user_id"] = user.pk
    request.session["reset_otp_id"] = otp_record.pk

def forgot_password(request):

    if request.method == "POST":

        # A fresh request invalidates any verification granted by an earlier flow.
        _clear_password_reset_session(request)

        email = request.POST.get(
            "email",
            "",
        ).strip().lower()

        user = (
            User.objects
            .filter(
                email__iexact=email,
                is_active=True,
            )
            .first()
        )

        if user:
            reused_code = False
            try:
                otp_record = issue_otp(user, "reset")
            except OTPRequestThrottled as e:
                # Reuse the still-valid code for this account during the cooldown,
                # but never carry forward its previous verification state.
                otp_record = OTPVerification.objects.filter(
                    user=user,
                    purpose="reset",
                    used=False,
                    expires_at__gt=timezone.now(),
                ).order_by("-created_at").first()
                messages.warning(request, str(e))
                if not otp_record:
                    return redirect("forgot_password")
                reused_code = True
            except Exception:
                messages.error(request, "Could not send password reset email right now.")
                return redirect("forgot_password")

            _bind_password_reset_otp(request, user, otp_record)
            if not reused_code:
                messages.info(request, "If an eligible account matches this address, a password reset code has been sent.")
            return redirect("verify_reset_otp")

        messages.info(request, "If an eligible account matches this address, a password reset code has been sent.")

    return render(
        request,
        "travel/forgot_password.html",
    )


# ============================================================
# VERIFY PASSWORD RESET OTP
# ============================================================

def verify_reset_otp(request):

    user_id = request.session.get(
        "reset_user_id"
    )
    otp_id = request.session.get("reset_otp_id")

    user = (
        get_object_or_404(
            User,
            pk=user_id,
        )
        if user_id
        else None
    )

    if not user or not otp_id:
        _clear_password_reset_session(request)
        return redirect(
            "forgot_password"
        )

    if request.method == "POST":

        otp = request.POST.get(
            "otp",
            "",
        ).strip()

        ok, msg = verify_otp(
            user,
            "reset",
            otp,
            otp_id=otp_id,
        )

        if ok:
            request.session["reset_verified_user_id"] = user.pk
            request.session["reset_verified_otp_id"] = otp_id
            request.session["reset_verified_at"] = timezone.now().isoformat()

            return redirect(
                "set_new_password"
            )

        messages.error(
            request,
            msg,
        )

    return render(
        request,
        "travel/verify_otp.html",
        {
            "purpose": "password reset",
            "email": user.email,
        },
    )


# ============================================================
# SET NEW PASSWORD
# ============================================================

def set_new_password(request):

    user_id = request.session.get(
        "reset_user_id"
    )

    otp_id = request.session.get("reset_otp_id")
    verified_user_id = request.session.get("reset_verified_user_id")
    verified_otp_id = request.session.get("reset_verified_otp_id")
    verified_at = request.session.get("reset_verified_at")

    if (
        not user_id
        or not otp_id
        or verified_user_id != user_id
        or verified_otp_id != otp_id
        or not verified_at
    ):
        _clear_password_reset_session(request)
        return redirect(
            "forgot_password"
        )

    user = get_object_or_404(
        User,
        pk=user_id,
    )
    try:
        verified_time = datetime.fromisoformat(verified_at)
        if timezone.is_naive(verified_time):
            verified_time = timezone.make_aware(verified_time)
        if timezone.now() - verified_time > timedelta(minutes=15):
            _clear_password_reset_session(request)
            return redirect("forgot_password")
    except (TypeError, ValueError):
        _clear_password_reset_session(request)
        return redirect("forgot_password")
    verified_otp_exists = OTPVerification.objects.filter(
        pk=otp_id,
        user_id=user_id,
        purpose="reset",
        used=True,
    ).exists()
    if not verified_otp_exists:
        _clear_password_reset_session(request)
        return redirect("forgot_password")

    if request.method == "POST":

        password1 = request.POST.get(
            "password1",
            "",
        )

        password2 = request.POST.get(
            "password2",
            "",
        )

        if len(password1) < 8:

            messages.error(
                request,
                "Password must contain at least 8 characters.",
            )

        elif password1 != password2:

            messages.error(
                request,
                "Passwords do not match.",
            )

        else:
            try:
                validate_password(password1, user=user)
            except ValidationError as e:
                for error in e.messages:
                    messages.error(request, error)
            else:
                user.set_password(password1)
                user.save(update_fields=["password"])
                _clear_password_reset_session(request)
                messages.success(request, "Password updated successfully.")
                return redirect("login")

    return render(
        request,
        "travel/set_new_password.html",
    )


# ============================================================
# LOGOUT
# ============================================================

@require_POST
def logout_view(request):

    logout(request)

    messages.success(
        request,
        "You have been logged out successfully.",
    )

    return redirect(
        "home"
    )


# ============================================================
# DASHBOARD
# ============================================================

@login_required
def dashboard(request):

    trips = (
        request.user.trips
        .select_related(
            "destination"
        )
        .order_by(
            "-created_at"
        )[:6]
    )

    preferences = get_preferences(
        request.user
    )

    joined_group_trips = (
        Trip.objects.filter(group__members=request.user)
        .exclude(user=request.user)
        .distinct()
        .select_related("destination")
    )

    return render(
        request,
        "travel/dashboard.html",
        {
            "trips": trips,
            "joined_group_trips": joined_group_trips,
            "trip_count": request.user.trips.count(),
            "saved_count": request.user.saved_trips.count(),
            "learned": preference_summary(
                request.user
            ),
            "preferences": sorted(
                preferences.as_dict().items(),
                key=lambda x: x[1],
                reverse=True,
            )[:5],
        },
    )


# ============================================================
# PROFILE
# ============================================================

@login_required
def profile(request):

    profile_obj, _ = (
        Profile.objects.get_or_create(
            user=request.user
        )
    )

    UserPreference.objects.get_or_create(
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

        return redirect(
            "profile"
        )

    return render(
        request,
        "travel/profile.html",
        {
            "form": form,
            "profile": profile_obj,
            "preferences": get_preferences(
                request.user
            ),
        },
    )


# ============================================================
# DESTINATIONS
# ============================================================

def destinations(request):

    query = request.GET.get(
        "q",
        "",
    ).strip()

    interest = request.GET.get(
        "interest",
        "",
    ).strip().lower()

    min_rating = request.GET.get(
        "rating",
        "",
    ).strip()

    items = Destination.objects.all()

    if query:

        items = items.filter(
            Q(name__icontains=query)
            | Q(state__icontains=query)
            | Q(best_for__icontains=query)
        )

    if interest:

        items = items.filter(
            best_for__icontains=interest
        )

    if min_rating:

        try:

            items = items.filter(
                rating__gte=float(
                    min_rating
                )
            )

        except ValueError:
            pass

    return render(
        request,
        "travel/destinations.html",
        {
            "destinations": items.distinct(),
            "q": query,
            "interest": interest,
            "rating": min_rating,
        },
    )


# ============================================================
# DESTINATION DETAILS
# ============================================================

def destination_detail(request, pk):

    destination = get_object_or_404(
        Destination,
        pk=pk,
    )

    attractions = sorted(
        destination.attractions.all(),
        key=lambda a: (
            -a.hidden_gem_score,
            -a.sustainability_score,
        ),
    )

    reviews = (
        destination.reviews
        .select_related("user")
    )

    user_review = None

    if request.user.is_authenticated:

        user_review = (
            destination.reviews
            .filter(
                user=request.user
            )
            .first()
        )

    review_form = ReviewForm(instance=user_review)

    average_rating = (
        reviews.aggregate(
            avg=Avg("rating")
        )["avg"]
        or float(destination.rating)
    )

    return render(
        request,
        "travel/destination_detail.html",
        {
            "destination": destination,
            "attractions": attractions,
            "clusters": cluster_summary(
                attractions
            ),
            "reviews": reviews[:10],
            "review_form": review_form,
            "user_review": user_review,
            "review_avg": round(
                float(average_rating),
                1,
            ),
            "review_count": reviews.count(),
        },
    )


# ============================================================
# CREATE / UPDATE REVIEW
# ============================================================

def recalculate_destination_rating(destination):
    """Recalculate destination rating based on current reviews or reset to default."""
    average_rating = (
        destination.reviews
        .aggregate(
            value=Avg("rating")
        )["value"]
    )
    if average_rating is not None:
        destination.rating = round(float(average_rating), 1)
    else:
        destination.rating = 4.5
    destination.save(update_fields=["rating"])
    return destination.rating


@login_required
def review_destination(request, pk):
    destination = get_object_or_404(
        Destination,
        pk=pk,
    )

    if request.method != "POST":
        return redirect("destination_detail", pk=pk)

    review = (
        destination.reviews
        .filter(
            user=request.user
        )
        .first()
    )

    form = ReviewForm(
        request.POST,
        instance=review,
    )

    if form.is_valid():
        review_obj = form.save(commit=False)
        review_obj.user = request.user
        review_obj.destination = destination
        review_obj.save()

        recalculate_destination_rating(destination)

        action_msg = "updated" if review else "saved"
        messages.success(
            request,
            f"Your review was {action_msg} successfully.",
        )
    else:
        messages.error(
            request,
            "Please correct the review form errors (rating must be 1 to 5).",
        )

    return redirect(
        "destination_detail",
        pk=pk,
    )


# ============================================================
# DELETE REVIEW
# ============================================================

@login_required
@require_POST
def delete_review(request, pk):
    destination = get_object_or_404(
        Destination,
        pk=pk,
    )

    review = (
        destination.reviews
        .filter(
            user=request.user
        )
        .first()
    )

    if review:
        review.delete()
        recalculate_destination_rating(destination)
        messages.success(
            request,
            "Your review has been deleted.",
        )
    else:
        messages.warning(
            request,
            "No review found to delete.",
        )

    return redirect(
        "destination_detail",
        pk=pk,
    )


# ============================================================
# HELPFUL REVIEW
# ============================================================

@login_required
@require_POST
def helpful_review(
    request,
    review_id,
):
    review = get_object_or_404(
        Review,
        pk=review_id,
    )

    if review.user == request.user:
        messages.warning(request, "You cannot mark your own review as helpful.")
        return redirect(
            "destination_detail",
            pk=review.destination_id,
        )

    voted_reviews = request.session.get("helpful_reviews", [])
    if review_id in voted_reviews:
        messages.info(request, "You have already marked this review as helpful.")
    else:
        review.helpful_count += 1
        review.save(
            update_fields=[
                "helpful_count"
            ]
        )
        voted_reviews.append(review_id)
        request.session["helpful_reviews"] = voted_reviews
        request.session.modified = True
        messages.success(request, "Thank you! You marked this review as helpful.")

    return redirect(
        "destination_detail",
        pk=review.destination_id,
    )


# ============================================================
# TRIP PLANNER
# ============================================================

@login_required
def trip_planner(request):
    form_data = request.POST or None
    ai_prefill_note = ""
    is_prefill = request.method == "POST" and request.POST.get("action") == "prefill"
    if is_prefill and request.POST.get("trip_brief", "").strip():
        brief = request.POST.get("trip_brief", "").strip()
        parsed = interpret_trip_request(brief, list(Destination.objects.values("id", "name")))
        mutable = request.POST.copy()
        destination_name = (parsed.get("destination") or "").strip().lower()
        destination = next((d for d in Destination.objects.all() if d.name.lower() == destination_name), None)
        if destination:
            mutable["destination"] = str(destination.pk)
        # Override browser-rendered default values with extracted values, then let the user review them.
        for field in ("title", "start_date", "end_date", "travelers", "budget", "interest", "pace"):
            if parsed.get(field) not in (None, ""):
                mutable[field] = str(parsed[field])
        form_data = mutable
        if destination:
            ai_prefill_note = f"Trip brief interpreted using {parsed.get('source', 'local')} parsing. Review the fields below, then generate your itinerary."
        elif mutable.get("destination"):
            ai_prefill_note = "No destination name was detected in the brief. Your selected destination was kept. Review the remaining fields before generating."
        else:
            ai_prefill_note = "We could not match a destination from your description. Select one from the destination field, review the details, then generate."
    form = TripForm(form_data)

    if request.method == "POST" and not is_prefill and form.is_valid():
        trip = form.save(commit=False)
        trip.user = request.user
        trip.save()
        count = _build_itinerary(trip, request.user)
        if count:
            messages.success(request, f"Personalized itinerary generated with {count} activity item(s).")
            return redirect("trip_detail", pk=trip.pk)
        messages.error(request, "SmartTrip could not generate an itinerary for this destination.")
        trip.delete()

    return render(request, "travel/trip_planner.html", {"form": form, "ai_prefill_note": ai_prefill_note})


# ============================================================
# SMARTTRIP AI COPILOT
# ============================================================

@login_required
def trip_copilot(request, pk=None):
    all_destinations = list(Destination.objects.all().order_by("name"))

    # CASE A: Existing Trip Copilot & Conversational Refinement
    if pk is not None:
        trip = get_object_or_404(
            Trip.objects.select_related("destination"),
            pk=pk,
        )
        is_owner = (trip.user == request.user)
        is_member = is_owner or (hasattr(trip, "group") and trip.group.members.filter(id=request.user.id).exists())
        if not is_member:
            messages.error(request, "You do not have permission to access this trip's Copilot.")
            return redirect("dashboard")

        if request.method == "POST":
            action = request.POST.get("action", "")

            # 1. Conversational Refinement
            if action == "refine":
                if not is_owner:
                    messages.error(request, "Only the trip owner can apply itinerary changes.")
                    return redirect("trip_copilot_detail", pk=pk)

                prompt = request.POST.get("prompt", "").strip()
                if prompt:
                    refinement_result = refine_itinerary_with_prompt(trip, prompt)
                    if refinement_result.get("success"):
                        repaired_items = refinement_result.get("repaired_items", [])
                        if repaired_items:
                            trip.items.all().delete()
                            for it in repaired_items:
                                ItineraryItem.objects.create(
                                    trip=trip,
                                    day_number=it["day"],
                                    attraction=it["attraction"],
                                    start_time=it.get("start") or time(9, 0),
                                    end_time=it.get("end"),
                                    score=it.get("score", 0),
                                    reason=it.get("reason", ""),
                                )
                        messages.success(request, refinement_result.get("summary", "Itinerary refined successfully."))
                    else:
                        messages.warning(
                            request,
                            refinement_result.get("summary", "Could not interpret refinement request safely."),
                        )
                return redirect("trip_copilot_detail", pk=pk)

            # 2. Switch to one of the 3 alternative profiles
            elif action == "apply_alternative":
                if not is_owner:
                    messages.error(request, "Only the trip owner can switch planning profiles.")
                    return redirect("trip_copilot_detail", pk=pk)

                alt_key = request.POST.get("alternative_key", "")
                alternatives = generate_copilot_alternatives(
                    trip.destination, trip.days, trip.budget, trip.travelers, trip.interest, trip.pace, user=request.user
                )
                chosen = next((a for a in alternatives if a["key"] == alt_key), None)
                if chosen:
                    trip.items.all().delete()
                    for d in chosen["days"]:
                        for it in d["items"]:
                            ItineraryItem.objects.create(
                                trip=trip,
                                day_number=d["day_number"],
                                attraction=it["attraction"],
                                start_time=time(int(it["time"].split(":")[0]), int(it["time"].split(":")[1])),
                                end_time=time(int(it["end_time"].split(":")[0]), int(it["end_time"].split(":")[1])) if it.get("end_time") else None,
                                score=it["score"],
                                reason=it["reason"],
                            )
                    messages.success(request, f"Trip itinerary switched to the '{chosen['title']}' alternative profile.")
                return redirect("trip_copilot_detail", pk=pk)

        groups = []
        for day in range(1, trip.days + 1):
            groups.append({
                "number": day,
                "items": trip.items.filter(day_number=day).select_related("attraction"),
                "weather": weather_context(day, trip.destination, trip.start_date + timedelta(days=day - 1)),
            })

        route_points = []
        for item in trip.items.select_related("attraction").order_by("day_number", "start_time", "pk"):
            attr = item.attraction
            if attr.latitude is not None and attr.longitude is not None:
                try:
                    lat, lon = float(attr.latitude), float(attr.longitude)
                    if -90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0:
                        route_points.append({
                            "name": attr.name,
                            "lat": lat,
                            "lon": lon,
                            "day": item.day_number,
                            "time": item.start_time.strftime("%H:%M") if item.start_time else "",
                            "category": attr.category or "Attraction",
                            "cost": attr.estimated_cost or 0,
                            "reason": item.reason,
                        })
                except (ValueError, TypeError):
                    pass

        alternatives = generate_copilot_alternatives(
            trip.destination, trip.days, trip.budget, trip.travelers, trip.interest, trip.pace, user=request.user
        )

        total_expenses = trip.expenses.aggregate(total=Sum("amount"))["total"] or 0
        remaining_budget = max(0, trip.budget - total_expenses)

        return render(
            request,
            "travel/copilot_detail.html",
            {
                "trip": trip,
                "is_owner": is_owner,
                "groups": groups,
                "route_points": route_points,
                "map_config": _map_configuration(),
                "alternatives": alternatives,
                "total_expenses": total_expenses,
                "remaining_budget": remaining_budget,
            },
        )

    # CASE B: Standalone / New Trip Copilot
    trip_brief = request.POST.get("trip_brief", "") or request.GET.get("brief", "")
    destination_id = request.POST.get("destination") or request.GET.get("destination")
    try:
        days = int(request.POST.get("days") or request.GET.get("days") or 3)
    except (ValueError, TypeError):
        days = 3

    try:
        budget = int(str(request.POST.get("budget") or request.GET.get("budget") or 15000).replace(",", ""))
    except (ValueError, TypeError):
        budget = 15000

    try:
        travelers = int(request.POST.get("travelers") or request.GET.get("travelers") or 2)
    except (ValueError, TypeError):
        travelers = 2

    # Keep user-controlled parameters within the ranges the existing brief
    # parser supports before they reach algorithms that allocate per-day data.
    if not 1 <= days <= 30:
        messages.error(request, "Choose a trip duration from 1 to 30 days.")
        days = 3
    if not 1 <= travelers <= 50:
        messages.error(request, "Choose between 1 and 50 travelers.")
        travelers = 2
    if not 0 <= budget <= 2_147_483_647:
        messages.error(request, "Enter a valid non-negative budget.")
        budget = 15000

    interest = request.POST.get("interest") or request.GET.get("interest") or "culture"
    pace = request.POST.get("pace") or request.GET.get("pace") or "balanced"

    parsed_info = None

    if request.method == "POST" and request.POST.get("action") == "parse_brief" and trip_brief.strip():
        parsed = interpret_trip_request(trip_brief, [{"id": d.id, "name": d.name} for d in all_destinations])
        parsed_info = parsed
        dest_name = (parsed.get("destination") or "").lower()
        matched_dest = next((d for d in all_destinations if d.name.lower() == dest_name), None)
        if matched_dest:
            destination_id = str(matched_dest.id)
        if parsed.get("days"):
            days = parsed["days"]
        if parsed.get("budget"):
            budget = parsed["budget"]
        if parsed.get("travelers"):
            travelers = parsed["travelers"]
        if parsed.get("interest"):
            interest = parsed["interest"]
        if parsed.get("pace"):
            pace = parsed["pace"]

    create_errors = []
    if request.method == "POST" and request.POST.get("action") == "create_from_alternative":
        try:
            submitted_days = int(request.POST.get("days", ""))
        except (TypeError, ValueError):
            submitted_days = 0
        try:
            submitted_travelers = int(request.POST.get("travelers", ""))
        except (TypeError, ValueError):
            submitted_travelers = 0
        try:
            submitted_budget = int(str(request.POST.get("budget", "")).replace(",", ""))
        except (TypeError, ValueError):
            submitted_budget = -1

        if not 1 <= submitted_days <= 30:
            create_errors.append("Trip duration must be from 1 to 30 days.")
        if not 1 <= submitted_travelers <= 50:
            create_errors.append("Travelers must be from 1 to 50.")
        if not 0 <= submitted_budget <= 2_147_483_647:
            create_errors.append("Enter a valid non-negative budget.")
        if not any(str(destination.pk) == str(destination_id) for destination in all_destinations):
            create_errors.append("Choose an available destination.")
        if interest not in dict(Trip.INTERESTS):
            create_errors.append("Choose a valid trip interest.")
        if pace not in dict(Trip._meta.get_field("pace").choices):
            create_errors.append("Choose a valid travel pace.")
        if request.POST.get("alternative_key") not in {"budget_saver", "balanced_explorer", "hidden_gems_eco"}:
            create_errors.append("Choose one of the available itinerary alternatives.")
        submitted_title = request.POST.get("title", "").strip()
        if len(submitted_title or f"{next((d.name for d in all_destinations if str(d.pk) == str(destination_id)), 'Trip')} AI Trip") > 180:
            create_errors.append("Trip title must be 180 characters or fewer.")
        if create_errors:
            messages.error(request, " ".join(create_errors))

    # Action: Instantiate Chosen Alternative
    if request.method == "POST" and request.POST.get("action") == "create_from_alternative" and not create_errors:
        dest = next(d for d in all_destinations if str(d.pk) == str(destination_id))
        alt_key = request.POST.get("alternative_key", "balanced_explorer")
        title = request.POST.get("title") or f"{dest.name} AI Trip"
        alternatives = generate_copilot_alternatives(dest, days, budget, travelers, interest, pace, user=request.user)
        chosen = next((a for a in alternatives if a["key"] == alt_key), None)
        if chosen and chosen.get("stop_count", 0):
            start_date = timezone.localdate() + timedelta(days=14)
            with transaction.atomic():
                trip = Trip.objects.create(
                    user=request.user,
                    destination=dest,
                    title=title,
                    start_date=start_date,
                    end_date=start_date + timedelta(days=days - 1),
                    travelers=travelers,
                    budget=budget,
                    interest=interest,
                    pace=pace,
                )
                itinerary_items = []
                for day in chosen["days"]:
                    for item in day["items"]:
                        itinerary_items.append(ItineraryItem(
                            trip=trip,
                            day_number=day["day_number"],
                            attraction=item["attraction"],
                            start_time=time(int(item["time"].split(":")[0]), int(item["time"].split(":")[1])),
                            end_time=time(int(item["end_time"].split(":")[0]), int(item["end_time"].split(":")[1])) if item.get("end_time") else None,
                            score=item["score"],
                            reason=item["reason"],
                        ))
                ItineraryItem.objects.bulk_create(itinerary_items)
            messages.success(request, f"Trip '{trip.title}' created from '{chosen['title']}' alternative profile!")
            return redirect("trip_copilot_detail", pk=trip.pk)
        messages.error(request, "That alternative has no schedulable activities, so no trip was created.")

    selected_destination = None
    alternatives = []
    if destination_id:
        try:
            selected_destination = next((d for d in all_destinations if str(d.id) == str(destination_id)), None)
            if selected_destination:
                alternatives = generate_copilot_alternatives(
                    selected_destination, days, budget, travelers, interest, pace, user=request.user
                )
        except Exception:
            pass
    elif all_destinations:
        selected_destination = all_destinations[0]
        destination_id = str(selected_destination.id)
        alternatives = generate_copilot_alternatives(
            selected_destination, days, budget, travelers, interest, pace, user=request.user
        )

    return render(
        request,
        "travel/copilot.html",
        {
            "all_destinations": all_destinations,
            "selected_destination": selected_destination,
            "destination_id": str(destination_id or ""),
            "days": days,
            "budget": budget,
            "travelers": travelers,
            "interest": interest,
            "pace": pace,
            "trip_brief": trip_brief,
            "parsed_info": parsed_info,
            "alternatives": alternatives,
        },
    )


def _can_access_trip(trip, user):
    """Checks whether a user has permission to view/save the trip: owner, staff, or group member."""
    if not user.is_authenticated:
        return False
    if user.is_staff or trip.user_id == user.id:
        return True
    if hasattr(trip, "group") and trip.group.members.filter(id=user.id).exists():
        return True
    return False


# ============================================================
# TRIP DETAILS
# ============================================================

@login_required
def trip_detail(request, pk):

    trip = get_object_or_404(
        Trip.objects.select_related(
            "destination"
        ),
        pk=pk,
    )
    if not _can_access_trip(trip, request.user):
        messages.error(request, "You do not have permission to view this trip.")
        return redirect("dashboard")

    groups = []

    for day in range(
        1,
        trip.days + 1,
    ):

        items = list(
            trip.items.filter(day_number=day)
            .select_related("attraction", "weather_alternative")
        )
        previous_item = None
        previous_coordinates = None
        for item in items:
            coordinates = _map_coordinates(item.attraction)
            item.has_map_coordinates = coordinates is not None
            if coordinates:
                item.map_latitude = coordinates["latitude"]
                item.map_longitude = coordinates["longitude"]
            distance = (
                haversine_km(previous_coordinates, coordinates)
                if previous_coordinates is not None and coordinates is not None
                else None
            )
            item.previous_item_id = previous_item.pk if previous_item else ""
            item.distance_from_previous_km = round(distance, 1) if distance is not None else None
            previous_item = item
            previous_coordinates = coordinates

        groups.append(
            {
                "number": day,
                "items": items,
                "weather": weather_context(
                    day, trip.destination, trip.start_date + timedelta(days=day - 1)
                ),
            }
        )

    route_points = []
    for item in trip.items.select_related("attraction").order_by("day_number", "start_time", "pk"):
        attraction = item.attraction
        coordinates = _map_coordinates(attraction)
        if coordinates:
            route_points.append({
                "item_id": item.pk,
                "name": attraction.name,
                "lat": coordinates["latitude"],
                "lon": coordinates["longitude"],
                "day": item.day_number,
                "time": item.start_time.strftime("%H:%M") if item.start_time else "",
                "category": attraction.category or "Attraction",
                "cost": int(attraction.estimated_cost or 0),
                "duration": float(attraction.duration_hours) if attraction.duration_hours else 2.0,
                "reason": item.reason or "",
            })

    return render(
        request,
        "travel/trip_detail.html",
        {
            "trip": trip,
            "groups": groups,
            "route_points": route_points,
            "map_config": _map_configuration(),
            "quality": itinerary_quality(
                trip
            ),
            "sustainability": trip_sustainability(
                trip
            ),
            "feasibility": check_feasibility(
                trip
            ),
            "saved": SavedTrip.objects.filter(
                user=request.user,
                trip=trip,
            ).exists(),
        },
    )


# ============================================================
# SAVE TRIP
# ============================================================

@login_required
@require_POST
def save_trip(request, pk):

    trip = get_object_or_404(
        Trip,
        pk=pk,
    )
    if not _can_access_trip(trip, request.user):
        messages.error(request, "You do not have permission to save this trip.")
        return redirect("dashboard")

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


# ============================================================
# REMOVE SAVED TRIP
# ============================================================

@login_required
@require_POST
def remove_saved_trip(request, pk):

    trip = get_object_or_404(
        Trip,
        pk=pk,
    )

    SavedTrip.objects.filter(
        user=request.user,
        trip=trip,
    ).delete()

    messages.success(
        request,
        "Trip removed from saved trips.",
    )

    return redirect(
        "saved_trips"
    )


# ============================================================
# RECOMMENDATION FEEDBACK
# ============================================================

@login_required
@require_POST
def feedback(
    request,
    pk,
    item_id,
    action,
):

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

    if action not in {
        "like",
        "dislike",
    }:

        messages.error(
            request,
            "Invalid feedback action.",
        )

        return redirect(
            "trip_detail",
            pk=pk,
        )

    previous = RecommendationFeedback.objects.filter(
        user=request.user, trip=trip, attraction=item.attraction
    ).order_by("id").first()
    if previous is None:
        RecommendationFeedback.objects.create(
            user=request.user, trip=trip, attraction=item.attraction, action=action
        )
        update_preference_from_feedback(request.user, item.attraction, action)
    elif previous.action != action:
        previous.action = action
        previous.save(update_fields=["action"])
        update_preference_from_feedback(request.user, item.attraction, action)

    messages.success(
        request,
        "Feedback recorded. Your recommendations will learn from it.",
    )

    return redirect(
        "trip_detail",
        pk=pk,
    )


# ============================================================
# BUDGET
# ============================================================

@login_required
def budget(request, pk):
    trip = get_object_or_404(
        Trip,
        pk=pk,
        user=request.user,
    )

    allocation_form = BudgetAllocationForm(
        request.POST if request.method == "POST" and request.POST.get("action") == "save_allocations" else None,
        trip=trip,
    )
    form = ExpenseForm(
        request.POST if request.method == "POST" and request.POST.get("action") != "save_allocations" else None
    )

    if request.method == "POST" and request.POST.get("action") == "save_allocations" and allocation_form.is_valid():
        allocation_form.save()
        messages.success(request, "Budget allocations saved.")
        return redirect("budget", pk=pk)

    if request.method == "POST" and form.is_valid():
        expense = form.save(commit=False)
        expense.trip = trip
        expense.save()
        messages.success(request, "Expense added successfully.")
        return redirect("budget", pk=pk)

    expenses = trip.expenses.order_by("-created_at")
    total = expenses.aggregate(total=Sum("amount"))["total"] or 0
    remaining = max(0, trip.budget - total)

    # Estimated trip cost is a planning estimate, separate from actual expenses.
    estimated_trip_cost = trip.estimated_total
    estimated_overrun = max(0, estimated_trip_cost - trip.budget)

    spending_percentage = (
        min(100, round(total * 100 / trip.budget))
        if trip.budget > 0
        else (100 if total > 0 else 0)
    )

    # Daily burn rate analysis
    days = max(1, trip.days)
    daily_burn_rate = round(total / days)
    target_daily_budget = round(trip.budget / days) if trip.budget > 0 else 0

    # Aggregate recorded expenses by category for the chart.
    category_totals = list(
        expenses.values("category")
        .annotate(category_total=Sum("amount"))
        .order_by("-category_total")
    )
    category_labels = [item["category"] for item in category_totals]
    category_amounts = [float(item["category_total"]) for item in category_totals]
    category_chart_rows = [
        {
            "label": item["category"],
            "amount": item["category_total"],
            "share_pct": round(item["category_total"] * 100 / total) if total else 0,
        }
        for item in category_totals
    ]

    # Planned vs Actual Benchmarks
    benchmarks = [
        {"key": "Accommodation", "label": "Accommodation & Stay", "field": "accommodation_budget_pct", "icon": "fa-hotel"},
        {"key": "Food", "label": "Food & Dining", "field": "food_budget_pct", "icon": "fa-utensils"},
        {"key": "Transport", "label": "Transport & Flights", "field": "transport_budget_pct", "icon": "fa-plane"},
        {"key": "Activities", "label": "Activities & Sightseeing", "field": "activities_budget_pct", "icon": "fa-ticket"},
        {"key": "Miscellaneous", "label": "Miscellaneous", "field": "miscellaneous_budget_pct", "icon": "fa-basket-shopping"},
    ]

    actual_by_cat = defaultdict(Decimal)
    for exp in expenses:
        cat_norm = (exp.category or "").strip().lower()
        if any(w in cat_norm for w in ["hotel", "stay", "accommodation", "resort", "hostel"]):
            actual_by_cat["Accommodation"] += exp.amount
        elif any(w in cat_norm for w in ["food", "dining", "meal", "restaurant", "cafe", "snack"]):
            actual_by_cat["Food"] += exp.amount
        elif any(w in cat_norm for w in ["transport", "flight", "cab", "taxi", "train", "bus", "metro"]):
            actual_by_cat["Transport"] += exp.amount
        elif any(w in cat_norm for w in ["activity", "activities", "sightseeing", "ticket", "museum", "tour"]):
            actual_by_cat["Activities"] += exp.amount
        elif any(w in cat_norm for w in ["shop", "shopping", "misc", "miscellaneous", "other"]):
            actual_by_cat["Miscellaneous"] += exp.amount
        else:
            matched = False
            for b in benchmarks:
                if b["key"].lower() in cat_norm:
                    actual_by_cat[b["key"]] += exp.amount
                    matched = True
                    break
            if not matched:
                actual_by_cat["Miscellaneous"] += exp.amount

    planned_vs_actual = []

    raw_targets = [Decimal(trip.budget) * Decimal(getattr(trip, b["field"])) / Decimal(100) for b in benchmarks]
    target_values = [int(value) for value in raw_targets]
    remaining_units = max(0, int(trip.budget) - sum(target_values))
    remainder_order = sorted(
        range(len(raw_targets)),
        key=lambda index: (raw_targets[index] - target_values[index], -index),
        reverse=True,
    )
    for index in remainder_order[:remaining_units]:
        target_values[index] += 1

    category_alternatives = []
    for benchmark_index, b in enumerate(benchmarks):
        share_pct = int(getattr(trip, b["field"]))
        planned_val = target_values[benchmark_index]
        actual_val = actual_by_cat[b["key"]]
        pct_used = round((actual_val / planned_val) * 100) if planned_val > 0 else (100 if actual_val > 0 else 0)
        diff = planned_val - actual_val
        is_over = actual_val > planned_val

        status_class = "danger" if is_over else ("warning" if pct_used >= 80 else "success")
        status_text = "Over Budget" if is_over else ("Near Limit" if pct_used >= 80 else "On Track")

        planned_vs_actual.append({
            "key": b["key"],
            "label": b["label"],
            "share_pct": share_pct,
            "planned": planned_val,
            "actual": actual_val,
            "pct_used": min(100, pct_used),
            "diff": abs(diff),
            "is_over": is_over,
            "status_class": status_class,
            "status_text": status_text,
            "icon": b["icon"],
        })

        if is_over:
            if b["key"] == "Accommodation":
                category_alternatives.append({
                    "title": "Accommodation Savings Alternative",
                    "category": "Accommodation",
                    "description": "Consider booking boutique guesthouses or staying 2-3 metro stations outside the tourist center for lower room rates.",
                })
            elif b["key"] == "Food":
                category_alternatives.append({
                    "title": "Dining Cost Reduction Alternative",
                    "category": "Food",
                    "description": "Explore popular local street food lanes, heritage markets, and authentic regional thali spots instead of tourist-strip restaurants.",
                })
            elif b["key"] == "Transport":
                category_alternatives.append({
                    "title": "Transit Optimization Alternative",
                    "category": "Transport",
                    "description": "Switch from on-demand private cabs to public transit passes, metro routes, or pre-scheduled shared airport transfers.",
                })
            elif b["key"] == "Activities":
                category_alternatives.append({
                    "title": "Free Attraction Alternatives",
                    "category": "Activities",
                    "description": "Substitute paid attraction entries with free public heritage monuments, beaches, scenic viewpoints, and gardens.",
                })

    # Create insights from actual recorded expenses.
    spending_insights = []
    if not total:
        spending_insights.append(
            "Add expenses to unlock personalized spending insights."
        )
    else:
        if category_totals:
            top_category = category_totals[0]
            category_share = round(top_category["category_total"] * 100 / total)
            spending_insights.append(
                f"Your highest spending category is {top_category['category']} "
                f"({category_share}% of recorded expenses)."
            )

        if total > trip.budget:
            spending_insights.append(
                "Your recorded expenses have exceeded your trip budget."
            )
        elif spending_percentage >= 80:
            spending_insights.append(
                "You have used at least 80% of your trip budget. "
                "Review remaining expenses carefully."
            )
        else:
            spending_insights.append(
                f"You have ₹{remaining} remaining from your budget."
            )

        if daily_burn_rate > target_daily_budget and target_daily_budget > 0:
            spending_insights.append(
                f"Daily burn rate (₹{daily_burn_rate}/day) exceeds target daily budget (₹{target_daily_budget}/day)."
            )
        elif target_daily_budget > 0:
            spending_insights.append(
                f"Daily spending is on pace at ₹{daily_burn_rate}/day (Target: ₹{target_daily_budget}/day)."
            )

    budget_suggestions = []
    if category_alternatives:
        budget_suggestions.extend(category_alternatives)

    if estimated_overrun > 0:
        suggestion_data = [
            (
                "Choose a lower-cost stay",
                "Accommodation",
                "Compare budget hotels, hostels, and accommodation outside premium areas.",
            ),
            (
                "Reduce transport costs",
                "Transport",
                "Compare public transport, shared rides, and routes with fewer transfers.",
            ),
            (
                "Prioritize free attractions",
                "Activities",
                "Include beaches, parks, viewpoints, and other free attractions where available.",
            ),
            (
                "Set a daily food limit",
                "Food",
                "Plan meals in advance and compare local, affordable food options.",
            ),
        ]
        # Avoid duplicate titles
        existing_titles = {s["title"] for s in budget_suggestions}
        for title, cat, description in suggestion_data:
            if title not in existing_titles:
                budget_suggestions.append({
                    "title": title,
                    "category": cat,
                    "description": description,
                })

    optimization_gap = estimated_overrun

    return render(
        request,
        "travel/budget.html",
        {
            "trip": trip,
            "form": form,
            "allocation_form": allocation_form,
            "expenses": expenses,
            "total": total,
            "remaining": remaining,
            "estimated_trip_cost": estimated_trip_cost,
            "estimated_overrun": estimated_overrun,
            "spending_percentage": spending_percentage,
            "daily_burn_rate": daily_burn_rate,
            "target_daily_budget": target_daily_budget,
            "category_labels": category_labels,
            "category_amounts": category_amounts,
            "category_chart_rows": category_chart_rows,
            "planned_vs_actual": planned_vs_actual,
            "spending_insights": spending_insights,
            "budget_suggestions": budget_suggestions,
            "optimization_gap": optimization_gap,
        },
    )


@login_required
def edit_budget_expense(request, pk, expense_id):
    trip = get_object_or_404(Trip, pk=pk, user=request.user)
    expense = get_object_or_404(BudgetExpense, pk=expense_id, trip=trip)

    form = ExpenseForm(
        request.POST if request.method == "POST" else None,
        instance=expense,
    )
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Expense updated successfully.")
        return redirect("budget", pk=trip.pk)

    return render(
        request,
        "travel/budget_expense_edit.html",
        {
            "trip": trip,
            "form": form,
            "expense": expense,
        },
    )


@login_required
@require_POST
def delete_budget_expense(request, pk, expense_id):
    trip = get_object_or_404(Trip, pk=pk, user=request.user)
    expense = get_object_or_404(BudgetExpense, pk=expense_id, trip=trip)
    expense.delete()
    messages.success(request, "Expense deleted successfully.")
    return redirect("budget", pk=trip.pk)


# ============================================================
# SAVED TRIPS
# ============================================================

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
        {
            "saved": saved
        },
    )


# ============================================================
# RECOMMENDATIONS
# ============================================================

@login_required
def recommendations(request):

    all_destinations = Destination.objects.all().order_by("name")

    destination_id = request.GET.get(
        "destination"
    )

    if destination_id:
        destination = get_object_or_404(
            Destination,
            pk=destination_id,
        )
    else:
        destination = all_destinations.first()

    if destination is None:
        messages.error(
            request,
            "No destinations are available yet.",
        )
        return redirect(
            "destinations"
        )

    interest = request.GET.get(
        "interest",
        "culture",
    ).strip()

    pace = request.GET.get(
        "pace",
        "moderate",
    ).strip()

    class RecommendationProfile:
        pass

    profile = RecommendationProfile()
    profile.interest = interest
    profile.pace = pace
    profile.sustainability_priority = 4
    profile.include_hidden_gems = True
    profile.user = request.user

    valid_feedback_actions = {
        action for action, _label in RecommendationFeedback._meta.get_field("action").choices
    }
    latest_feedback_by_attraction = {}
    feedback_records = (
        RecommendationFeedback.objects
        .filter(
            user=request.user,
            attraction__destination=destination,
            action__in=valid_feedback_actions,
        )
        .order_by("created_at", "pk")
        .values_list("attraction_id", "action")
    )
    for attraction_id, action in feedback_records:
        # Collapse any legacy duplicate/conflicting rows to the latest valid
        # action so an attraction cannot receive both direct signals at once.
        latest_feedback_by_attraction[attraction_id] = action

    positive_feedback_ids = {
        attraction_id
        for attraction_id, action in latest_feedback_by_attraction.items()
        if action in {"like", "save"}
    }
    negative_feedback_ids = {
        attraction_id
        for attraction_id, action in latest_feedback_by_attraction.items()
        if action == "dislike"
    }
    profile._disliked_attraction_ids = negative_feedback_ids

    ranked = sorted(
        destination.attractions.all(),
        key=lambda attraction: recommendation_score(
            attraction,
            profile,
            positive_feedback_ids,
        ),
        reverse=True,
    )

    recommendations_data = []
    for attraction in ranked:
        score_breakdown = recommendation_score_breakdown(
            attraction,
            profile,
            positive_feedback_ids,
        )
        score = score_breakdown["score"]
        attraction.score_breakdown = score_breakdown
        explanation = explain(
            attraction,
            profile,
            score,
            positive_feedback_ids,
        )
        recommendations_data.append(
            (
                attraction,
                score,
                explanation,
            )
        )

    return render(
        request,
        "travel/recommendations.html",
        {
            "destination": destination,
            "destinations": all_destinations,
            "recommendations": recommendations_data,
            "interest": interest,
            "pace": pace,
        },
    )


# ============================================================
# WHAT-IF PLANNING
# ============================================================

@login_required
def what_if_view(request, pk):

    trip = get_object_or_404(
        Trip,
        pk=pk,
        user=request.user,
    )

    form = ScenarioForm(
        request.POST or None,
        initial={"preferred_interest": trip.interest, "pace": trip.pace},
    )

    result = None

    if request.method == "POST" and form.is_valid():

        scenario = form.save(
            commit=False
        )

        scenario.trip = trip

        result = what_if(
            trip,
            scenario.budget_change,
            scenario.extra_days,
            preferred_interest=scenario.preferred_interest,
            pace=form.cleaned_data.get("pace"),
        )

        scenario.result_summary = (
            f"Budget ₹{result['budget']}, "
            f"{result['days']} days, "
            f"estimated ₹{result['estimated']}, "
            f"interest={result['interest']}, "
            f"pace={result['pace']}, "
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


# ============================================================
# DYNAMIC REPLANNING
# ============================================================

@login_required
@require_POST
def replan(request, pk):
    trip = get_object_or_404(Trip, pk=pk, user=request.user)
    trigger = request.POST.get("trigger", "Weather-aware replan").strip() if request.method == "POST" else "Weather-aware replan"
    attractions = list(trip.destination.attractions.all())
    weather_sources = set()
    if "weather" in trigger.lower() or "rain" in trigger.lower() or "storm" in trigger.lower():
        weather_sources = {
            weather_context(day, trip.destination, trip.start_date + timedelta(days=day - 1)).get("source")
            for day in range(1, trip.days + 1)
        }
    likes = _feedback_ids(request.user)
    disliked = _disliked_ids(request.user)
    plan = repair_itinerary(trip, attractions, likes, disliked, trigger)
    if not plan:
        messages.error(request, "SmartTrip could not produce a feasible itinerary.")
        return redirect("trip_detail", pk=pk)
    changed = sum(1 for item in plan if item.get("changed"))
    with transaction.atomic():
        trip.items.all().delete()
        for item in plan:
            alternative = None
            if trip.weather_adaptive:
                alternative = alternative_for(attractions, item["day"], {item["attraction"].id}, item["attraction"].id)
            ItineraryItem.objects.create(
                trip=trip,
                day_number=item["day"],
                attraction=item["attraction"],
                start_time=item["start"],
                end_time=item.get("end"),
                score=item["score"],
                reason=item["reason"],
                weather_alternative=alternative,
            )
        TripReplanLog.objects.create(
            trip=trip,
            trigger=trigger or "Manual re-plan",
            action=f"Minimum-disruption repair completed. {changed} activity change(s) across {len(plan)} itinerary item(s).",
        )
    if changed:
        messages.success(request, f"SmartTrip repaired your itinerary with {changed} activity change(s), preserving unaffected activities.")
    elif weather_sources and "Open-Meteo forecast" not in weather_sources:
        messages.info(request, "No date-specific live forecast was available. The itinerary was preserved; offline demo weather does not trigger replanning.")
    else:
        messages.info(request, "No activity replacement was needed. SmartTrip preserved the existing itinerary to minimize disruption.")
    return redirect("trip_detail", pk=pk)


# ============================================================
# GROUP TRIPS
# ============================================================

@login_required
@require_http_methods(["GET", "POST"])
def group_trip(request, pk):
    trip = get_object_or_404(
        Trip,
        pk=pk,
    )

    group = GroupTrip.objects.filter(trip=trip).first()
    is_owner = request.user == trip.user or (group is not None and request.user == group.owner)
    if group is None:
        if not is_owner:
            messages.error(request, "You need an invitation to view this group trip.")
            return redirect("dashboard")
        if request.method == "POST" and request.POST.get("action") == "create_group":
            group = GroupTrip.objects.create(
                owner=trip.user,
                trip=trip,
                invite_code=secrets.token_urlsafe(18),
                invite_expires_at=timezone.now() + timedelta(days=30),
            )
            messages.success(request, "Group collaboration is ready. This invite expires in 30 days.")
            return redirect("group", pk=pk)
        return render(request, "travel/group_setup.html", {"trip": trip})

    is_member = is_owner or group.members.filter(id=request.user.id).exists()

    if not is_member:
        messages.error(
            request,
            "You need an invitation to view this group trip.",
        )
        return redirect("dashboard")

    if request.method == "POST":

        action = request.POST.get(
            "action",
            "add",
        )

        if action == "renew_invite":
            if not is_owner:
                messages.error(request, "Only the trip host can renew an invite.")
            else:
                group.invite_code = secrets.token_urlsafe(18)
                group.invite_expires_at = timezone.now() + timedelta(days=30)
                group.save(update_fields=["invite_code", "invite_expires_at"])
                messages.success(request, "A new invite code is active for 30 days.")
            return redirect("group", pk=pk)

        if action == "add":

            if not is_owner:
                messages.error(
                    request,
                    "Only the trip host can invite members.",
                )
                return redirect("group", pk=pk)

            username = request.POST.get(
                "username",
                "",
            ).strip()

            member = (
                User.objects
                .filter(
                    username=username
                )
                .first()
            )

            if not member:
                messages.error(
                    request,
                    f"User '{username}' was not found.",
                )
            elif member == group.owner or member == trip.user:
                messages.warning(
                    request,
                    f"{username} is already the trip host.",
                )
            elif group.members.filter(id=member.id).exists():
                messages.info(
                    request,
                    f"{username} is already in the group.",
                )
            else:
                group.members.add(member)
                messages.success(
                    request,
                    f"{username} was added to the group trip.",
                )

        elif action == "remove":

            if not is_owner:
                messages.error(
                    request,
                    "Only the trip host can remove members.",
                )
                return redirect("group", pk=pk)

            member_id = request.POST.get("member_id")
            member_to_remove = User.objects.filter(id=member_id).first()
            if member_to_remove and group.members.filter(id=member_to_remove.id).exists():
                group.members.remove(member_to_remove)
                messages.success(
                    request,
                    f"{member_to_remove.username} was removed from the group.",
                )

        elif action == "leave":

            if is_owner:
                messages.error(
                    request,
                    "The trip host cannot leave the group. You can manage members or delete the trip.",
                )
            else:
                group.members.remove(request.user)
                messages.success(
                    request,
                    f"You have left the group for '{trip.title}'.",
                )
                return redirect("dashboard")

        elif action == "vote":

            attraction_id = request.POST.get("attraction_id")
            vote_choice = request.POST.get("vote")

            if not attraction_id or vote_choice not in {"like", "dislike"}:
                messages.error(request, "Choose a valid attraction and vote.")
                return redirect("group", pk=pk)

            try:
                attraction_id = int(attraction_id)
            except (TypeError, ValueError):
                messages.error(request, "Choose a valid attraction and vote.")
                return redirect("group", pk=pk)

            attraction = get_object_or_404(
                Attraction, id=attraction_id, destination_id=trip.destination_id
            )
            previous = RecommendationFeedback.objects.filter(
                user=request.user, trip=trip, attraction=attraction
            ).order_by("id").first()
            if previous is None:
                RecommendationFeedback.objects.create(
                    user=request.user, trip=trip, attraction=attraction,
                    action=vote_choice,
                )
                update_preference_from_feedback(request.user, attraction, vote_choice)
            elif previous.action != vote_choice:
                previous.action = vote_choice
                previous.save(update_fields=["action"])
                update_preference_from_feedback(request.user, attraction, vote_choice)
            messages.success(request, f"Recorded your {vote_choice} for {attraction.name}.")

        elif action == "optimize":

            if not is_owner:
                messages.error(
                    request,
                    "Only the trip host can optimize the group itinerary.",
                )
                return redirect("group", pk=pk)

            all_members = list(group.members.all())
            if group.owner not in all_members:
                all_members.append(group.owner)

            group_pref_map = aggregate_group_preferences(
                all_members,
                minority_weight=0.30,
            )

            best_interest = trip.interest
            if group_pref_map:
                top_interest, top_score = next(iter(group_pref_map.items()))
                if top_score > group_pref_map.get(trip.interest, 0.5) + 0.01:
                    best_interest = top_interest

            trip.interest = best_interest
            member_ids = [member.pk for member in all_members]
            group_feedback = list(
                RecommendationFeedback.objects.filter(trip=trip, user_id__in=member_ids)
                .values("attraction_id", "action")
            )
            votes = Counter()
            for feedback in group_feedback:
                votes[(feedback["attraction_id"], feedback["action"])] += 1
            trip._group_users = all_members
            trip._group_feedback_ids = {
                attraction_id for (attraction_id, action), count in votes.items()
                if action == "like" and count > votes[(attraction_id, "dislike")]
            }
            trip._disliked_attraction_ids = {
                attraction_id for (attraction_id, action), count in votes.items()
                if action == "dislike" and count > votes[(attraction_id, "like")]
            }
            try:
                with transaction.atomic():
                    trip.save(update_fields=["interest"])
                    _build_itinerary(trip, trip.user)
            finally:
                for attribute in ("_group_users", "_group_feedback_ids", "_disliked_attraction_ids"):
                    if hasattr(trip, attribute):
                        delattr(trip, attribute)

            messages.success(
                request,
                (
                    f"Group itinerary successfully optimized for '{best_interest.title()}' "
                    "with minority satisfaction protection."
                ),
            )

        return redirect(
            "group",
            pk=pk,
        )

    all_members = list(group.members.all())
    if group.owner not in all_members:
        all_members.append(group.owner)

    group_pref_dict = aggregate_group_preferences(
        all_members,
        minority_weight=0.30,
    )
    group_preferences = list(group_pref_dict.items())

    # Collect itinerary attractions with voting stats
    items = list(
        trip.items.select_related("attraction")
        .order_by("day_number", "id")
    )

    feedbacks = RecommendationFeedback.objects.filter(trip=trip)
    for item in items:
        attr_feedbacks = [f for f in feedbacks if f.attraction_id == item.attraction_id]
        item.likes = sum(1 for f in attr_feedbacks if f.action == "like")
        item.dislikes = sum(1 for f in attr_feedbacks if f.action == "dislike")
        my_vote = next((f.action for f in attr_feedbacks if f.user_id == request.user.id), None)
        item.user_vote = my_vote

    return render(
        request,
        "travel/group.html",
        {
            "trip": trip,
            "group": group,
            "is_owner": is_owner,
            "members": group.members.all(),
            "all_members": all_members,
            "group_preferences": group_preferences,
            "items": items,
            "invite_expired": bool(not group.invite_expires_at or group.invite_expires_at <= timezone.now()),
        },
    )


@login_required
def join_group_trip(request):
    code = (
        request.GET.get("code")
        or request.POST.get("invite_code")
        or ""
    ).strip().upper()

    if request.method == "POST":
        if not code:
            messages.error(
                request,
                "Please enter an invite code to join a group trip.",
            )
            return render(request, "travel/join_group.html")

        group = GroupTrip.objects.filter(invite_code__iexact=code).first()
        if not group:
            messages.error(
                request,
                "No active group invitation matched that code. Check with the host for a current code.",
            )
            return render(
                request,
                "travel/join_group.html",
                {"code": code},
            )

        if not group.invite_expires_at or group.invite_expires_at <= timezone.now():
            messages.error(request, "This invite code has expired. Ask the host to renew it.")
            return render(request, "travel/join_group.html", {"code": ""})

        if request.user == group.owner or request.user == group.trip.user:
            messages.info(
                request,
                "You are already the host of this trip.",
            )
            return redirect("group", pk=group.trip.pk)

        if group.members.filter(id=request.user.id).exists():
            messages.info(
                request,
                "You are already a member of this group trip.",
            )
            return redirect("group", pk=group.trip.pk)

        group.members.add(request.user)
        messages.success(
            request,
            f"Welcome! You've joined the group for '{group.trip.title}'. You can now vote and collaborate on the itinerary.",
        )
        return redirect("group", pk=group.trip.pk)

    return render(
        request,
        "travel/join_group.html",
        {"code": code},
    )


# ============================================================
# AI ASSISTANT
# ============================================================

@login_required
@require_http_methods(["GET", "POST"])
def assistant(request, pk=None):
    if pk is not None:
        accessible_trips = Trip.objects.select_related("destination").filter(
            Q(user=request.user) | Q(group__members=request.user)
        ).distinct()
        trip = get_object_or_404(accessible_trips, pk=pk)
    else:
        trip = None
    answer = None
    source = None
    question = ""
    if request.method == "POST":
        question = request.POST.get("question", "").strip()
        context = {}
        if trip:
            scheduled_items = list(
                trip.items.select_related("attraction")
                .order_by("day_number", "start_time", "pk")
            )
            scheduled_recommendations = [
                {
                    "name": item.attraction.name,
                    "score": item.score,
                    "reason": item.reason,
                }
                for item in scheduled_items
            ]
            context = {
                "trip_title": trip.title,
                "destination": trip.destination.name,
                "destination_state": trip.destination.state,
                "days": trip.days,
                "travelers": trip.travelers,
                "budget_inr": trip.budget,
                "estimated_cost_inr": trip.estimated_total,
                "interest": trip.interest,
                "pace": trip.pace,
                "scheduled_activities": [item["name"] for item in scheduled_recommendations],
                "scheduled_recommendations": scheduled_recommendations,
            }

        pref = getattr(request.user, "preference", None)
        if pref:
            context["user_preferences"] = pref.as_dict()

        profile = getattr(request.user, "profile", None)
        if profile:
            context["user_interests"] = profile.interests
            context["travel_style"] = profile.travel_style

        # The authenticated user is used only by the local itinerary planner.
        # assistant_reply strips internal values from optional provider prompts.
        context["_user"] = request.user
        answer, source = assistant_reply(question, context)
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"answer": answer, "source": source})
    return render(request, "travel/assistant.html", {"answer": answer, "trip": trip, "answer_source": source, "question": question})


# ============================================================
# DELETE TRIP
# ============================================================

@login_required
@require_POST
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

    return redirect(
        "dashboard"
    )


# ============================================================
# DESTINATION COMPARISON
# ============================================================

@login_required
def compare_destinations(request):
    submitted = request.GET.get("compare") == "1" or "ids" in request.GET
    raw_ids = [value.strip() for value in request.GET.getlist("ids") if value.strip()]
    selected_ids = []
    selected = []
    selection_error = ""

    if submitted:
        if len(raw_ids) not in {2, 3}:
            selection_error = "Choose two or three distinct destinations to compare."
        else:
            try:
                selected_ids = [int(value) for value in raw_ids]
            except (TypeError, ValueError):
                selection_error = "One or more destination selections are invalid. Choose from the list."

            if not selection_error and len(set(selected_ids)) != len(selected_ids):
                selection_error = "Choose each destination only once."

    all_destinations = list(
        Destination.objects.annotate(review_count=Count("reviews")).order_by("name", "pk")
    )
    if submitted and not selection_error:
        destinations_by_id = {destination.pk: destination for destination in all_destinations}
        if any(destination_id not in destinations_by_id for destination_id in selected_ids):
            selection_error = "One or more selected destinations are no longer available. Choose from the list."
        else:
            selected = [destinations_by_id[destination_id] for destination_id in selected_ids]
    else:
        selected = []

    category_counts = defaultdict(list)
    attraction_counts = defaultdict(int)
    for row in (
        Attraction.objects.filter(destination_id__in=[item.pk for item in selected])
        .values("destination_id", "category")
        .annotate(count=Count("pk"))
        .order_by("category")
    ):
        attraction_counts[row["destination_id"]] += row["count"]
        category = (row["category"] or "").strip()
        if category:
            category_counts[row["destination_id"]].append(
                {"name": category, "count": row["count"]}
            )

    for destination in selected:
        destination.attraction_count = attraction_counts[destination.pk]
        destination.attraction_categories = category_counts[destination.pk]
        destination.average_daily_cost_display = f"₹{destination.average_daily_cost:,}"

    selection_slots = [
        {"number": number, "value": raw_ids[number - 1] if len(raw_ids) >= number else ""}
        for number in (1, 2, 3)
    ]

    return render(
        request,
        "travel/compare.html",
        {
            "destinations": selected,
            "all_destinations": all_destinations,
            "selection_slots": selection_slots,
            "selection_error": selection_error,
            "selection_submitted": submitted,
        },
    )


# ============================================================
# PDF EXPORT
# ============================================================

@login_required
def export_trip_pdf(request, pk):

    trip = get_object_or_404(
        Trip,
        pk=pk,
        user=request.user,
    )

    pdf = trip_pdf(
        trip
    )

    response = HttpResponse(
        pdf.getvalue(),
        content_type="application/pdf",
    )

    safe_title = slugify(trip.title)[:80] or f"trip-{trip.pk}"

    response[
        "Content-Disposition"
    ] = (
        f'attachment; '
        f'filename="{safe_title}_SmartTrip.pdf"'
    )

    return response


# ============================================================
# DECISION LAB
# ============================================================

@login_required
def decision_lab(request, pk):
    trip = get_object_or_404(
        Trip.objects.select_related("destination"),
        pk=pk,
        user=request.user,
    )
    attractions = list(trip.destination.attractions.all())
    feedback_ids = _feedback_ids(request.user)

    options = optimize_pareto(trip, attractions, feedback_ids=feedback_ids)
    for option in options:
        option["comparison"] = itinerary_comparison_breakdown(
            trip,
            option.get("attractions", []),
            attractions,
            feedback_ids=feedback_ids,
        )
    scores = {a.id: recommendation_score(a, trip, feedback_ids) for a in attractions}
    knapsack = select_attractions_knapsack(attractions, trip.budget, trip.travelers, scores)

    graph_route = None
    if options and options[0].get("attractions") and len(options[0]["attractions"]) >= 2:
        first_attr = options[0]["attractions"][0]
        last_attr = options[0]["attractions"][-1]
        if (
            getattr(first_attr, "latitude", None) is not None
            and getattr(last_attr, "latitude", None) is not None
            and first_attr.id != last_attr.id
        ):
            graph_route = plan_geographic_path(
                attractions,
                first_attr.id,
                last_attr.id,
                algorithm="astar",
            )

    context = {
        "trip": trip,
        "algorithm_name": "NSGA-II",
        "candidate_count": len(attractions),
        "options": options,
        "graph_route": graph_route,
        "knapsack": knapsack,
    }
    return render(request, "travel/decision_lab.html", context)


# ============================================================
# ADMIN ANALYTICS
# ============================================================

@login_required
@user_passes_test(
    lambda user: user.is_staff
)
def admin_analytics(request):
    total_feedback = RecommendationFeedback.objects.count()
    feedback_stats = list(
        RecommendationFeedback.objects
        .values("action")
        .annotate(count=Count("id"))
        .order_by("-count")
    )
    for fb in feedback_stats:
        fb["pct"] = round((fb["count"] / total_feedback * 100), 1) if total_feedback else 0

    avg_rating_val = (
        Review.objects
        .aggregate(
            value=Avg("rating")
        )["value"]
    )
    avg_rating = round(float(avg_rating_val), 1) if avg_rating_val is not None else 0.0

    all_trips = list(Trip.objects.all())
    trips_count = len(all_trips)
    avg_trip_days = round(sum(t.days for t in all_trips) / trips_count, 1) if trips_count else 0
    avg_trip_budget = round(Trip.objects.aggregate(avg=Avg("budget"))["avg"] or 0)
    total_itinerary_items = ItineraryItem.objects.count()
    total_attractions = Attraction.objects.count()
    group_trips_count = GroupTrip.objects.count()
    group_collaborators_count = User.objects.filter(group_trips__isnull=False).distinct().count()
    total_tracked_expenses = BudgetExpense.objects.aggregate(total=Sum("amount"))["total"] or 0
    saved_trips_count = SavedTrip.objects.count()

    popular_destinations = list(
        Destination.objects
        .annotate(trip_count=Count("trips"))
        .filter(trip_count__gt=0)
        .order_by("-trip_count", "name")[:5]
    )

    current_month = timezone.localdate().replace(day=1)

    month_starts = []
    for offset in range(11, -1, -1):
        month_index = current_month.year * 12 + current_month.month - 1 - offset
        year, zero_based_month = divmod(month_index, 12)
        month_starts.append(date(year, zero_based_month + 1, 1))

    next_month_index = current_month.year * 12 + current_month.month
    next_year, next_zero_based_month = divmod(next_month_index, 12)
    next_month = date(next_year, next_zero_based_month + 1, 1)

    range_start = timezone.make_aware(
        datetime.combine(month_starts[0], time.min)
    )
    range_end = timezone.make_aware(
        datetime.combine(next_month, time.min)
    )

    # Group timestamps in Python instead of using MySQL's TruncMonth.
    # This avoids dependence on MySQL time-zone tables for date conversion.
    monthly_trip_counts = {
        (month.year, month.month): 0
        for month in month_starts
    }

    trip_dates = Trip.objects.filter(
        created_at__gte=range_start,
        created_at__lt=range_end,
    ).values_list("created_at", flat=True)

    for created_at in trip_dates:
        local_created_at = timezone.localtime(created_at)
        month_key = (local_created_at.year, local_created_at.month)

        if month_key in monthly_trip_counts:
            monthly_trip_counts[month_key] += 1

    trip_trend = [
        {
            "label": month.strftime("%b %Y"),
            "count": monthly_trip_counts[(month.year, month.month)],
        }
        for month in month_starts
    ]

    context = {
        "users": User.objects.count(),
        "verified_users": (
            Profile.objects
            .filter(
                email_verified=True
            )
            .count()
        ),
        "trips": trips_count,
        "avg_trip_days": avg_trip_days,
        "avg_trip_budget": avg_trip_budget,
        "total_itinerary_items": total_itinerary_items,
        "total_attractions": total_attractions,
        "group_trips_count": group_trips_count,
        "group_collaborators_count": group_collaborators_count,
        "total_tracked_expenses": total_tracked_expenses,
        "saved_trips_count": saved_trips_count,
        "reviews": Review.objects.count(),
        "avg_rating": avg_rating,
        "destinations": Destination.objects.count(),
        "popular": popular_destinations,
        "trip_trend": trip_trend,
        "trip_trend_has_data": any(item["count"] for item in trip_trend),
        "popular_chart": [
            {"label": destination.name, "count": destination.trip_count}
            for destination in popular_destinations
        ],
        "top_reviewed": (
            Destination.objects
            .annotate(
                review_count=Count("reviews"),
                avg_user_rating=Avg("reviews__rating"),
            )
            .filter(review_count__gt=0)
            .order_by("-review_count", "name")[:5]
        ),
        "feedback": feedback_stats,
        "total_feedback": total_feedback,
    }

    return render(
        request,
        "travel/admin_analytics.html",
        context,
    )
