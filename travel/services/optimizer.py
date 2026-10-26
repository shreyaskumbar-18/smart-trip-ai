from datetime import time

from .recommendation import recommendation_score, explain
from .route_algorithms import nearest_neighbor_two_opt


PACE_ACTIVITIES = {
    "relaxed": 2,
    "balanced": 3,
    "packed": 4,
}


def _pace_per_day(trip):
    return PACE_ACTIVITIES.get(trip.pace, 3)


def _diversify_selection(ranked, limit):
    """Select high-scoring attractions while avoiding excessive category repetition."""
    if limit <= 0:
        return []

    selected = []
    used_ids = set()
    category_counts = {}

    for attraction in ranked:
        category = (attraction.category or "").strip().lower()

        if category_counts.get(category, 0) >= 2 and len(selected) < limit:
            continue

        selected.append(attraction)
        used_ids.add(attraction.id)
        category_counts[category] = category_counts.get(category, 0) + 1

        if len(selected) >= limit:
            return selected

    # Fill remaining slots if category balancing skipped anything.
    for attraction in ranked:
        if attraction.id not in used_ids:
            selected.append(attraction)
            used_ids.add(attraction.id)
            if len(selected) >= limit:
                break

    return selected


def _distance(a, b):
    """Return great-circle distance in kilometres using the Haversine formula."""
    if a.latitude is None or a.longitude is None or b.latitude is None or b.longitude is None:
        return None
    from math import asin, cos, radians, sin, sqrt
    lat1, lon1 = radians(float(a.latitude)), radians(float(a.longitude))
    lat2, lon2 = radians(float(b.latitude)), radians(float(b.longitude))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    hav = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 6371.0 * 2 * asin(min(1.0, sqrt(hav)))


def _route_order(attractions):
    """Order attractions with nearest-neighbour followed by 2-opt improvement."""
    return nearest_neighbor_two_opt(list(attractions), _distance)


def optimize_trip(trip, attractions, feedback_ids=None):
    """
    Generate a personalized multi-day itinerary.

    The optimizer:
    - ranks attractions using recommendation scoring
    - respects travel pace
    - balances attraction categories
    - distributes attractions across trip days
    - orders attractions geographically when coordinates exist
    - avoids repeating attractions
    - provides explanations for every selected attraction
    """

    feedback_ids = set(feedback_ids or [])
    attractions = list(attractions)

    if not attractions or trip.days <= 0:
        return []

    per_day = _pace_per_day(trip)

    ranked = sorted(
        attractions,
        key=lambda attraction: recommendation_score(
            attraction,
            trip,
            feedback_ids,
        ),
        reverse=True,
    )

    max_items = min(
        trip.days * per_day,
        len(ranked),
    )

    selected = _diversify_selection(
        ranked,
        max_items,
    )

    if not selected:
        return []

    # Spread selected POIs over the trip before route ordering.
    day_buckets = [[] for _ in range(trip.days)]

    for index, attraction in enumerate(selected):
        day_buckets[index % trip.days].append(attraction)

    # Geographically order attractions within each day.
    for index in range(len(day_buckets)):
        day_buckets[index] = _route_order(day_buckets[index])

    slots = [9, 13, 17, 19]
    plan = []

    for day_index, day_attractions in enumerate(day_buckets):
        day_number = day_index + 1

        for position, attraction in enumerate(day_attractions):
            slot_hour = slots[min(position, len(slots) - 1)]

            score = recommendation_score(
                attraction,
                trip,
                feedback_ids,
            )

            reason = explain(
                attraction,
                trip,
                score,
            )

            if not reason or not reason.strip():
                reason = (
                    "Recommended based on its overall match "
                    f"with your trip preferences. "
                    f"Recommendation score: {score:.1f}/100."
                )

            plan.append(
                {
                    "day": day_number,
                    "attraction": attraction,
                    "start": time(slot_hour, 0),
                    "score": score,
                    "reason": reason,
                }
            )

    return plan


def itinerary_quality(trip):
    """
    Calculate itinerary quality using:
    - coverage against the available attraction pool
    - category variety
    - sustainability
    - crowd pressure

    The coverage target respects the selected pace, but never
    penalizes a destination for having fewer unique attractions
    than the theoretical daily target.
    """

    items = list(
        trip.items.select_related("attraction")
    )

    if not items:
        return 0

    per_day = _pace_per_day(trip)

    available_count = trip.destination.attractions.count()
    expected_items = min(
        trip.days * per_day,
        available_count,
    )

    coverage = (
        min(100, len(items) / expected_items * 100)
        if expected_items
        else 0
    )

    categories = {
        (item.attraction.category or "").strip().lower()
        for item in items
        if item.attraction.category
    }

    variety = min(
        100,
        len(categories) / min(4, max(1, len(items))) * 100,
    )

    sustainability = (
        sum(
            float(item.attraction.sustainability_score or 0)
            for item in items
        )
        / len(items)
    )

    crowd = (
        sum(
            float(item.attraction.crowd_level or 0)
            for item in items
        )
        / len(items)
    )

    score = (
        coverage * 0.35
        + variety * 0.20
        + sustainability * 0.25
        + (100 - crowd) * 0.20
    )

    return round(min(100, max(0, score)), 1)
