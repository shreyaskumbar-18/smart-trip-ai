from ..models import ItineraryItem, TripReplanLog
from .route_algorithms import haversine_km

PACE_LIMITS = {"relaxed": 2, "balanced": 3, "packed": 4}


def check_feasibility(trip):
    """
    Check whether the current trip is feasible.

    Checks:
    - estimated budget
    - trip duration
    - number of travelers
    - itinerary availability
    - daily itinerary distribution
    """

    issues = []

    estimated = trip.estimated_total

    # ---------------------------------------------------------
    # Budget
    # ---------------------------------------------------------

    if estimated > trip.budget:
        issues.append(
            f"Estimated cost ₹{estimated} exceeds your budget "
            f"by ₹{estimated - trip.budget}."
        )

    # ---------------------------------------------------------
    # Trip duration
    # ---------------------------------------------------------

    if trip.days > 14:
        issues.append(
            "Trip duration is long. Review transport and "
            "accommodation costs."
        )

    # ---------------------------------------------------------
    # Group size
    # ---------------------------------------------------------

    if trip.travelers > 10:
        issues.append(
            "Large group. Group planning is recommended."
        )

    # ---------------------------------------------------------
    # Itinerary
    # ---------------------------------------------------------

    items = list(
        trip.items.select_related("attraction")
    )

    if not items:
        issues.append(
            "No itinerary activities have been generated yet."
        )

    # ---------------------------------------------------------
    # Check empty days
    # ---------------------------------------------------------

    active_days = {
        item.day_number
        for item in items
    }

    empty_days = [
        day
        for day in range(1, trip.days + 1)
        if day not in active_days
    ]

    if empty_days:
        issues.append(
            f"No activities are scheduled for day(s): "
            f"{', '.join(map(str, empty_days))}."
        )

    # ---------------------------------------------------------
    # Check overloaded days
    # ---------------------------------------------------------

    daily_counts = {}

    for item in items:
        daily_counts[item.day_number] = (
            daily_counts.get(item.day_number, 0) + 1
        )

    overloaded_days = [
        day
        for day, count in daily_counts.items()
        if count > 4
    ]

    if overloaded_days:
        issues.append(
            f"Day(s) {', '.join(map(str, overloaded_days))} "
            "contain too many activities."
        )

    hard_issues = []
    recommendations = []
    by_day = {}
    for item in items:
        if not 1 <= item.day_number <= trip.days:
            hard_issues.append(f"Activity {item.attraction.name} is scheduled outside the trip dates.")
            continue
        if item.attraction.destination_id != trip.destination_id:
            hard_issues.append(f"Activity {item.attraction.name} is outside the trip destination.")
        by_day.setdefault(item.day_number, []).append(item)

    for day_number, day_items in by_day.items():
        day_items.sort(key=lambda item: (item.start_time is None, item.start_time, item.pk))
        seen = set()
        previous_end = None
        previous_attraction = None
        distance_km = 0.0
        complete_route = True
        for item in day_items:
            attraction = item.attraction
            if item.attraction_id in seen:
                recommendations.append(f"{attraction.name} appears more than once on day {day_number}.")
            seen.add(item.attraction_id)
            duration = float(attraction.duration_hours or 0)
            if duration <= 0 or duration > 12:
                recommendations.append(f"{attraction.name} has an unusual visit-duration estimate; review its schedule.")
            if item.start_time:
                start_minutes = item.start_time.hour * 60 + item.start_time.minute
                end_minutes = (
                    item.end_time.hour * 60 + item.end_time.minute
                    if item.end_time else start_minutes + max(0, round(duration * 60))
                )
                if item.end_time and end_minutes <= start_minutes:
                    hard_issues.append(f"{attraction.name} has an end time that is not after its start time.")
                if previous_end is not None and start_minutes < previous_end:
                    hard_issues.append(f"Scheduled activities overlap on day {day_number}.")
                previous_end = max(previous_end or end_minutes, end_minutes)
            if previous_attraction is not None:
                segment = haversine_km(previous_attraction, attraction)
                if segment is None:
                    complete_route = False
                else:
                    distance_km += segment
            previous_attraction = attraction
        if complete_route and distance_km > 80:
            recommendations.append(f"Day {day_number} covers about {distance_km:.1f} straight-line km between stops; allow for road distance and travel time.")
        elif not complete_route:
            recommendations.append(f"Day {day_number} route distance is incomplete because one or more stops lack coordinates.")

    issues.extend(hard_issues)
    issues.extend(recommendations)

    # ---------------------------------------------------------
    # Final result
    # ---------------------------------------------------------

    return {
        "feasible": not issues,
        "issues": issues,
        "hard_issues": hard_issues,
        "recommendations": recommendations,
        "estimated_cost": estimated,
        "scheduled_activities": len(items),
        "empty_days": empty_days,
    }


def what_if(trip, budget_change=0, extra_days=0, preferred_interest=None, pace=None):
    """
    Preview a hypothetical itinerary for changed budget, duration, interest,
    or pace without modifying the saved trip or its itinerary.
    """
    from copy import copy
    from datetime import timedelta

    from .optimizer import PACE_ACTIVITIES, deduplicate_attractions, optimize_trip
    from ..models import RecommendationFeedback
    from .knapsack import select_attractions_knapsack
    from .recommendation import recommendation_score

    new_budget = max(
        0,
        trip.budget + budget_change,
    )

    new_days = max(
        1,
        trip.days + extra_days,
    )

    estimated = (
        new_days
        * trip.destination.average_daily_cost
        * trip.travelers
    )

    simulated_trip = copy(trip)
    simulated_trip.budget = new_budget
    simulated_trip.end_date = trip.start_date + timedelta(days=new_days - 1)
    valid_interests = {value for value, _label in trip.INTERESTS}
    valid_paces = {value for value, _label in trip._meta.get_field("pace").choices}
    simulated_trip.interest = preferred_interest if preferred_interest in valid_interests else trip.interest
    simulated_trip.pace = pace if pace in valid_paces else trip.pace

    liked_ids = set(RecommendationFeedback.objects.filter(
        user=trip.user,
        action="like",
    ).values_list("attraction_id", flat=True))
    attractions = deduplicate_attractions(list(trip.destination.attractions.all()))
    plan = optimize_trip(
        simulated_trip,
        attractions,
        feedback_ids=liked_ids,
        concise_explanations=True,
    )
    first_choice_ticket_estimated = sum(
        (item["attraction"].estimated_cost or 0) * trip.travelers
        for item in plan
    )
    budget_optimized = first_choice_ticket_estimated > new_budget
    if budget_optimized:
        scores = {
            attraction.id: recommendation_score(attraction, simulated_trip, liked_ids)
            for attraction in attractions
        }
        selection = select_attractions_knapsack(
            attractions,
            budget=new_budget,
            travelers=trip.travelers,
            scores=scores,
            max_items=new_days * PACE_ACTIVITIES.get(simulated_trip.pace, 3),
        )
        plan = optimize_trip(
            simulated_trip,
            selection["selected"],
            feedback_ids=liked_ids,
            concise_explanations=True,
        )

    has_itinerary = bool(plan)
    budget_feasible = estimated <= new_budget
    feasible = budget_feasible and has_itinerary
    if not has_itinerary:
        if budget_optimized:
            feasibility_message = f"No itinerary could be generated within the ₹{new_budget} attraction-ticket limit and schedule constraints."
        else:
            feasibility_message = "No itinerary could be generated from the available attractions and schedule limits."
    elif not budget_feasible:
        feasibility_message = f"The destination-average trip-cost estimate exceeds the simulated budget by ₹{estimated - new_budget}. Attraction ticket estimates are shown separately."
    else:
        feasibility_message = "The destination-average trip-cost estimate is within budget and an itinerary was generated. Attraction ticket spend is estimated separately."
    if budget_optimized and has_itinerary:
        feasibility_message += " Lower-cost attraction options were selected to keep stored ticket estimates within the scenario budget."

    return {
        "budget": new_budget,
        "days": new_days,
        "estimated": estimated,
        "interest": simulated_trip.interest,
        "pace": simulated_trip.pace,
        "itinerary": plan,
        "ticket_estimated": sum(
            (item["attraction"].estimated_cost or 0) * trip.travelers
            for item in plan
        ),
        "budget_optimized": budget_optimized,
        "has_itinerary": has_itinerary,
        "budget_feasible": budget_feasible,
        "feasibility_message": feasibility_message,
        "feasible": feasible,
    }


def replan_trip(trip, reason="Manual re-planning"):
    """
    Rebuild the itinerary for an existing trip.

    The existing itinerary is removed and a new optimized
    itinerary is generated.
    """

    from .optimizer import optimize_trip
    from ..models import RecommendationFeedback

    # ---------------------------------------------------------
    # Get destination attractions
    # ---------------------------------------------------------

    attractions = list(
        trip.destination.attractions.all()
    )

    # ---------------------------------------------------------
    # Get attractions previously liked by the user
    # ---------------------------------------------------------

    feedback_ids = set(
        RecommendationFeedback.objects.filter(
            user=trip.user,
            action="like",
        ).values_list(
            "attraction_id",
            flat=True,
        )
    )

    # ---------------------------------------------------------
    # Store old itinerary count
    # ---------------------------------------------------------

    old_items = list(
        trip.items.select_related("attraction")
    )

    old_count = len(old_items)

    # ---------------------------------------------------------
    # Generate new itinerary
    # ---------------------------------------------------------

    new_plan = optimize_trip(
        trip,
        attractions,
        feedback_ids,
    )

    # ---------------------------------------------------------
    # Remove old itinerary
    # ---------------------------------------------------------

    trip.items.all().delete()

    # ---------------------------------------------------------
    # Create new itinerary
    # ---------------------------------------------------------

    created_items = []

    for item in new_plan:
        created_items.append(
            ItineraryItem.objects.create(
                trip=trip,
                day_number=item["day"],
                attraction=item["attraction"],
                start_time=item["start"],
                score=item["score"],
                reason=item["reason"],
            )
        )

    # ---------------------------------------------------------
    # Record re-planning event
    # ---------------------------------------------------------

    TripReplanLog.objects.create(
        trip=trip,
        trigger=reason,
        action=(
            f"Regenerated itinerary with "
            f"{len(created_items)} activity item(s)."
        ),
    )

    # ---------------------------------------------------------
    # Return result
    # ---------------------------------------------------------

    return {
        "old_count": old_count,
        "new_count": len(created_items),
        "items": created_items,
        "reason": reason,
    }
