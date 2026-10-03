from ..models import ItineraryItem, TripReplanLog


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

    # ---------------------------------------------------------
    # Final result
    # ---------------------------------------------------------

    return {
        "feasible": not issues,
        "issues": issues,
        "estimated_cost": estimated,
        "scheduled_activities": len(items),
        "empty_days": empty_days,
    }


def what_if(trip, budget_change=0, extra_days=0):
    """
    Evaluate a hypothetical change to budget or trip duration.
    """

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

    feasible = estimated <= new_budget

    return {
        "budget": new_budget,
        "days": new_days,
        "estimated": estimated,
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