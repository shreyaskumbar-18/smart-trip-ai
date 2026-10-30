"""Minimum-disruption itinerary repair for weather and activity disruptions."""
from datetime import time
from .recommendation import recommendation_score, explain
from .weather import alternative_for, weather_context
from .optimizer import visit_duration_minutes

OUTDOOR_CATEGORIES = {"nature", "adventure", "relaxation"}


def repair_itinerary(trip, attractions, feedback_ids=None, disliked_ids=None, trigger="Weather-aware replan"):
    """Preserve existing itinerary items unless a disruption gives a reason to replace them.

    Returns dictionaries compatible with the existing ItineraryItem creation flow.
    If the trip has no existing plan or the trigger requests full regeneration, use the optimizer.
    """
    from .optimizer import optimize_trip
    attractions = list(attractions)
    feedback_ids = set(feedback_ids or [])
    disliked_ids = set(disliked_ids or [])
    trip._disliked_attraction_ids = disliked_ids
    current = list(trip.items.select_related("attraction").order_by("day_number", "start_time", "pk"))
    scheduled_attraction_ids = {item.attraction_id for item in current}
    trigger_text = (trigger or "").lower()
    if not current or any(token in trigger_text for token in ("full regenerate", "regenerate all", "start over")):
        plan = optimize_trip(trip, attractions, feedback_ids)
        return [{**item, "changed": True, "change_reason": "Generated a fresh optimized itinerary."} for item in plan]

    repaired = []
    used_ids = set()
    changed_count = 0
    for item in current:
        attraction = item.attraction
        day = item.day_number
        trip_date = trip.start_date + __import__("datetime").timedelta(days=day - 1)
        weather = weather_context(day, trip.destination, trip_date)
        is_weather_trigger = any(word in trigger_text for word in ("weather", "rain", "storm", "outdoor"))
        category = (attraction.category or "").lower()
        # Demo conditions are illustrative and must not mutate a real plan.
        has_date_forecast = weather.get("source") == "Open-Meteo forecast"
        affected = is_weather_trigger and has_date_forecast and weather.get("condition") in {"Rain", "Thunderstorm", "Snow"} and category in OUTDOOR_CATEGORIES
        replacement = None
        if affected:
            # Never use a stop that is already scheduled elsewhere in the
            # itinerary as a replacement; doing so would duplicate that stop.
            replacement = alternative_for(
                attractions,
                day,
                used_ids | scheduled_attraction_ids,
                attraction.id,
                weather.get("condition"),
            )
        if replacement and replacement.id not in used_ids:
            changed_count += 1
            selected = replacement
            reason = f"Replaced {attraction.name} because {weather.get('condition', 'weather')} conditions affect outdoor activities. The rest of the schedule was preserved."
            score = recommendation_score(selected, trip, feedback_ids)
        else:
            selected = attraction
            reason = item.reason or explain(selected, trip, item.score)
            score = item.score
        used_ids.add(selected.id)
        start = item.start_time or time(9, 0)
        end = item.end_time
        if selected.id != attraction.id or end is None:
            end_minutes = start.hour * 60 + start.minute + visit_duration_minutes(selected)
            end = time(end_minutes // 60, end_minutes % 60) if end_minutes < 24 * 60 else None
        repaired.append({"day": day, "attraction": selected, "start": start, "end": end, "score": score, "reason": reason, "changed": selected.id != attraction.id, "change_reason": reason if selected.id != attraction.id else "Kept original activity to minimize disruption."})

    # If the weather trigger found no affected activities, preserve the plan and state that explicitly.
    if changed_count == 0:
        for item in repaired:
            if not item["changed"]:
                item["change_reason"] = "No replacement was necessary for this activity. It was preserved to minimize disruption."
    return repaired
