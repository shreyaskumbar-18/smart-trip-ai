"""Explainable content-based recommendations for trip places."""
from .algorithms import weather_suitability

RELATED = {
    'Nature': {'Nature', 'Photography', 'Adventure'},
    'History': {'History', 'Culture'},
    'Food': {'Food', 'Culture'},
    'Shopping': {'Shopping', 'Culture'},
    'Adventure': {'Adventure', 'Nature', 'Photography'},
    'Beaches': {'Beaches', 'Nature', 'Photography'},
    'Culture': {'Culture', 'History', 'Food'},
    'Photography': {'Photography', 'Nature', 'Beaches'},
}


def recommend_places(trip, forecast=None, limit=None):
    interests = set(trip.interest_list())
    places = list(trip.destination.places.all())
    forecast = forecast or []
    weather_score = 80.0
    if forecast:
        outdoor_days = [weather_suitability(d.get('condition'), d.get('temp_max'), True) for d in forecast]
        weather_score = sum(outdoor_days) / len(outdoor_days)
    ranked = []
    for place in places:
        related = set()
        for interest in interests:
            related.update(RELATED.get(interest, {interest}))
        interest_match = 100.0 if place.category in interests else (65.0 if place.category in related else 0.0)
        rating_score = min(100.0, float(place.rating) / 5.0 * 100.0)
        budget_fit = max(0.0, 100.0 - (float(place.entry_fee) / max(float(trip.total_budget), 1.0) * 100.0 * trip.number_of_people * 4.0))
        weather_fit = weather_score if place.is_outdoor else 95.0
        score = interest_match * 0.40 + rating_score * 0.25 + budget_fit * 0.20 + weather_fit * 0.15
        reasons = []
        if place.category in interests:
            reasons.append('matches your interests')
        elif place.category in related:
            reasons.append('matches a related interest')
        if place.rating >= 4.5:
            reasons.append('high visitor rating')
        if place.is_outdoor and weather_score < 50:
            reasons.append('weather fit is weaker')
        elif place.is_outdoor:
            reasons.append('good outdoor-weather fit')
        reason = ', '.join(reasons) if reasons else 'balanced score across interests, rating, budget and weather'
        ranked.append((place, round(score, 2), reason))
    ranked.sort(key=lambda row: row[1], reverse=True)
    return ranked[:limit] if limit else ranked
