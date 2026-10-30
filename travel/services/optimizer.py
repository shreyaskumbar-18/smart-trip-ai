from datetime import time
import re
import unicodedata

from .recommendation import recommendation_score, explain
from .route_algorithms import nearest_neighbor_two_opt


PACE_ACTIVITIES = {
    "relaxed": 2,
    "balanced": 3,
    "packed": 4,
}


def visit_duration_minutes(attraction):
    try:
        return max(30, round(float(attraction.duration_hours or 2.0) * 60))
    except (TypeError, ValueError, AttributeError):
        return 120


def schedule_attractions(attractions, start_hour=9, buffer_minutes=30, max_span_minutes=600):
    """Schedule visits from their stored duration estimates, with a planning buffer.

    The buffer is not a travel-time estimate. Road time remains unverified and
    should be checked separately in the map or with local providers.
    """
    cursor = start_hour * 60
    schedule = []
    for index, attraction in enumerate(attractions):
        if index:
            cursor += buffer_minutes
        duration = visit_duration_minutes(attraction)
        end = cursor + duration
        if end - start_hour * 60 > max_span_minutes or end >= 24 * 60:
            continue
        schedule.append({
            "attraction": attraction,
            "start": time(cursor // 60, cursor % 60),
            "end": time(end // 60, end % 60),
        })
        cursor = end
    return schedule


def _pace_per_day(trip):
    return PACE_ACTIVITIES.get(trip.pace, 3)


ITINERARY_COMPARISON_WEIGHTS = {
    "preference_match": 30,
    "coverage": 15,
    "category_variety": 10,
    "sustainability": 10,
    "crowd_comfort": 10,
    "route_compactness": 10,
    "budget_fit": 15,
}


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
    if not _has_valid_coordinates(a) or not _has_valid_coordinates(b):
        return None
    from math import asin, cos, radians, sin, sqrt
    lat1, lon1 = radians(float(a.latitude)), radians(float(a.longitude))
    lat2, lon2 = radians(float(b.latitude)), radians(float(b.longitude))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    hav = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 6371.0 * 2 * asin(min(1.0, sqrt(hav)))


def _has_valid_coordinates(attraction):
    try:
        latitude = float(attraction.latitude)
        longitude = float(attraction.longitude)
    except (AttributeError, TypeError, ValueError):
        return False
    return -90 <= latitude <= 90 and -180 <= longitude <= 180


def _route_order(attractions):
    """Order attractions with nearest-neighbour followed by 2-opt improvement."""
    return nearest_neighbor_two_opt(list(attractions), _distance)


def _attraction_name_key(attraction):
    """Normalize harmless name variants without merging distinct nearby stops."""
    name = unicodedata.normalize("NFKD", getattr(attraction, "name", "") or "")
    tokens = re.findall(r"[a-z0-9]+", name.casefold())
    aliases = {"fall": "falls", "waterfall": "falls", "waterfalls": "falls"}
    return tuple(aliases.get(token, token) for token in tokens)


def deduplicate_attractions(attractions):
    """Remove repeated records and same-name variants of the same POI.

    Name aliases such as "Jogini Falls" and "Jogini Waterfall" are treated as
    the same attraction when coordinates are absent or within 250 metres.
    Different names are never merged just because they are nearby.
    When duplicate rows differ in coordinate completeness, retain the one with
    usable coordinates for itinerary routing.
    """
    unique = []
    seen_ids = set()
    for attraction in attractions:
        attraction_id = getattr(attraction, "id", None)
        object_key = ("id", attraction_id) if attraction_id is not None else ("object", id(attraction))
        if object_key in seen_ids:
            continue
        seen_ids.add(object_key)

        name_key = _attraction_name_key(attraction)
        if not name_key:
            unique.append(attraction)
            continue
        duplicate_index = None
        for index, existing in enumerate(unique):
            if name_key != _attraction_name_key(existing):
                continue
            distance = _distance(existing, attraction)
            if distance is None or distance <= 0.25:
                duplicate_index = index
                break

        if duplicate_index is None:
            unique.append(attraction)
            continue

        existing = unique[duplicate_index]
        existing_has_coords = _has_valid_coordinates(existing)
        attraction_has_coords = _has_valid_coordinates(attraction)
        if attraction_has_coords and not existing_has_coords:
            unique[duplicate_index] = attraction

    return unique


def optimize_trip(trip, attractions, feedback_ids=None, concise_explanations=False):
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
    destination_id = getattr(trip, "destination_id", None)
    unique_attractions = deduplicate_attractions(attractions)
    destination_attractions = []
    for attraction in unique_attractions:
        attraction_destination = getattr(attraction, "destination_id", None)
        if destination_id is not None and attraction_destination is not None and attraction_destination != destination_id:
            continue
        destination_attractions.append(attraction)
    attractions = destination_attractions

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

    # Distribute selected POIs while respecting estimated visit durations and
    # the daily pace cap. The 30-minute inter-stop buffer is not drive time.
    day_buckets = [[] for _ in range(trip.days)]
    day_loads = [0 for _ in range(trip.days)]
    day_capacity = 10 * 60
    for attraction in selected:
        duration = visit_duration_minutes(attraction)
        candidates = sorted(range(trip.days), key=lambda index: (day_loads[index], index))
        for day_index in candidates:
            bucket = day_buckets[day_index]
            buffer = 30 if bucket else 0
            if len(bucket) < per_day and day_loads[day_index] + duration + buffer <= day_capacity:
                bucket.append(attraction)
                day_loads[day_index] += duration + buffer
                break

    # Geographically order attractions within each day.
    for index in range(len(day_buckets)):
        day_buckets[index] = _route_order(day_buckets[index])

    plan = []

    for day_index, day_attractions in enumerate(day_buckets):
        day_number = day_index + 1

        for scheduled in schedule_attractions(day_attractions):
            attraction = scheduled["attraction"]

            score = recommendation_score(
                attraction,
                trip,
                feedback_ids,
            )

            reason = explain(
                attraction,
                trip,
                score,
                feedback_ids,
                concise=concise_explanations,
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
                    "start": scheduled["start"],
                    "end": scheduled["end"],
                    "score": score,
                    "reason": reason,
                }
            )

    return plan


def _core_quality_components(trip, attractions, available_count, allow_missing_as_zero):
    count = len(attractions)
    per_day = _pace_per_day(trip)
    expected_items = min(
        trip.days * per_day,
        available_count,
    )

    coverage = (
        min(100, count / expected_items * 100)
        if expected_items
        else 0
    )

    categories = {
        (getattr(attraction, "category", "") or "").strip().lower()
        for attraction in attractions
        if getattr(attraction, "category", "")
    }
    variety = min(
        100,
        len(categories) / min(4, max(1, count)) * 100,
    )

    sustainability_values = [getattr(attraction, "sustainability_score", None) for attraction in attractions]
    crowd_values = [getattr(attraction, "crowd_level", None) for attraction in attractions]
    if allow_missing_as_zero:
        sustainability = sum(float(value or 0) for value in sustainability_values) / count if count else 0
        crowd_comfort = 100 - (sum(float(value or 0) for value in crowd_values) / count) if count else 0
    else:
        sustainability = (
            sum(float(value) for value in sustainability_values) / count
            if count and all(value is not None for value in sustainability_values)
            else None
        )
        crowd_comfort = (
            100 - sum(float(value) for value in crowd_values) / count
            if count and all(value is not None for value in crowd_values)
            else None
        )

    if not allow_missing_as_zero and count and any(
        not getattr(attraction, "category", None) for attraction in attractions
    ):
        variety = None

    return {
        "coverage": coverage if expected_items or allow_missing_as_zero else None,
        "category_variety": variety if categories or allow_missing_as_zero else None,
        "sustainability": sustainability,
        "crowd_comfort": crowd_comfort,
        "expected_stops": expected_items,
    }


def itinerary_quality(trip):
    """Return the existing persisted-itinerary quality score (0–100)."""
    items = list(trip.items.select_related("attraction"))
    if not items:
        return 0

    components = _core_quality_components(
        trip,
        [item.attraction for item in items],
        trip.destination.attractions.count(),
        allow_missing_as_zero=True,
    )

    score = (
        components["coverage"] * 0.35
        + components["category_variety"] * 0.20
        + components["sustainability"] * 0.25
        + components["crowd_comfort"] * 0.20
    )

    return round(min(100, max(0, score)), 1)


def itinerary_comparison_breakdown(trip, selected_attractions, available_attractions, feedback_ids=None):
    """Build an explainable Decision Lab score from stored data only.

    The returned weighted quality score is separate from hard attraction-budget
    feasibility. Missing components are excluded and the remaining weights are
    normalized to 100%; missing route data is never represented as zero km.
    """
    selected = deduplicate_attractions(list(selected_attractions or []))
    available = deduplicate_attractions(list(available_attractions or []))
    dimensions = _core_quality_components(
        trip,
        selected,
        len(available),
        allow_missing_as_zero=False,
    )

    preference_scores = [
        recommendation_score(attraction, trip, feedback_ids)
        for attraction in selected
    ]
    preference_match = (
        sum(preference_scores) / len(preference_scores)
        if preference_scores
        else None
    )

    route_distance = None
    route_compactness = None
    route_unavailable_reason = None
    if len(selected) < 2:
        route_unavailable_reason = "At least two selected stops are needed to compare a route."
    elif not all(_has_valid_coordinates(attraction) for attraction in selected):
        route_unavailable_reason = "Valid coordinates are missing for one or more selected stops."
    else:
        distances = [_distance(selected[index], selected[index + 1]) for index in range(len(selected) - 1)]
        direct_distance = _distance(selected[0], selected[-1])
        if direct_distance is None or any(distance is None for distance in distances):
            route_unavailable_reason = "A complete straight-line route could not be calculated from stored coordinates."
        else:
            route_distance = sum(distances)
            route_compactness = (
                100.0
                if route_distance == 0
                else min(100.0, direct_distance / route_distance * 100.0)
            )

    cost = None
    budget = None
    budget_fit = None
    budget_feasible = None
    budget_remaining = None
    try:
        budget = float(trip.budget)
        travelers = max(1, int(getattr(trip, "travelers", 1) or 1))
        stored_costs = [getattr(attraction, "estimated_cost", None) for attraction in selected]
        if budget >= 0 and all(value is not None for value in stored_costs):
            cost = sum(int(value or 0) for value in stored_costs) * travelers
            budget_feasible = cost <= budget
            budget_remaining = budget - cost
            budget_fit = (
                100.0 if cost == 0 else 0.0
            ) if budget == 0 else max(0.0, min(100.0, (budget - cost) / budget * 100.0))
    except (AttributeError, TypeError, ValueError, OverflowError):
        pass

    values = {
        "preference_match": preference_match,
        "coverage": dimensions["coverage"],
        "category_variety": dimensions["category_variety"],
        "sustainability": dimensions["sustainability"],
        "crowd_comfort": dimensions["crowd_comfort"],
        "route_compactness": route_compactness,
        "budget_fit": budget_fit,
    }
    available_weight = sum(
        ITINERARY_COMPARISON_WEIGHTS[key]
        for key, value in values.items()
        if value is not None
    )
    component_labels = {
        "preference_match": "Preference match",
        "coverage": "Coverage",
        "category_variety": "Category variety",
        "sustainability": "Sustainability",
        "crowd_comfort": "Lower crowd pressure",
        "route_compactness": "Route compactness (straight-line)",
        "budget_fit": "Attraction budget fit",
    }
    distinct_category_count = len({
        (getattr(attraction, "category", "") or "").strip().lower()
        for attraction in selected
        if getattr(attraction, "category", "")
    })
    component_details = {
        "preference_match": "Mean of the existing recommendation scores for selected stops.",
        "coverage": (
            f"{len(selected)} unique stops selected; target is {dimensions['expected_stops']} "
            f"based on pace and {len(available)} unique available attractions."
        ),
        "category_variety": (
            f"{distinct_category_count} distinct stored categories across selected stops."
        ),
        "sustainability": "Average stored sustainability score for selected stops.",
        "crowd_comfort": "100 minus the average stored crowd level for selected stops.",
        "route_compactness": "Direct endpoint distance divided by the complete straight-line route distance.",
        "budget_fit": (
            f"Stored attraction-ticket estimate ₹{cost} against the trip budget ₹{budget}."
            if cost is not None and budget is not None
            else "Stored attraction cost or trip budget is unavailable."
        ),
    }
    components = []
    for key, value in values.items():
        weight = ITINERARY_COMPARISON_WEIGHTS[key]
        normalized_weight = weight / available_weight if value is not None and available_weight else None
        if value is None:
            unavailable_reason = (
                route_unavailable_reason if key == "route_compactness"
                else "Required stored data is unavailable for this component."
            )
        else:
            unavailable_reason = ""
        components.append({
            "key": key,
            "label": component_labels[key],
            "detail": component_details[key],
            "score": value,
            "available": value is not None,
            "base_weight": weight,
            "normalized_weight_percent": normalized_weight * 100 if normalized_weight is not None else None,
            "weighted_points": value * normalized_weight if normalized_weight is not None else None,
            "unavailable_reason": unavailable_reason,
        })

    quality_score = (
        round(sum(component["weighted_points"] for component in components if component["weighted_points"] is not None), 1)
        if available_weight
        else None
    )
    return {
        "quality_score": quality_score,
        "quality_available": quality_score is not None,
        "components": components,
        "available_unique_count": len(available),
        "selected_unique_count": len(selected),
        "expected_stops": dimensions["expected_stops"],
        "route_compactness": route_compactness,
        "route_available": route_distance is not None,
        "route_distance_km": round(route_distance, 1) if route_distance is not None else None,
        "route_unavailable_reason": route_unavailable_reason,
        "attraction_cost": cost,
        "budget": budget,
        "budget_fit": budget_fit,
        "budget_feasible": budget_feasible,
        "budget_data_available": budget_feasible is not None,
        "budget_remaining": budget_remaining,
    }
