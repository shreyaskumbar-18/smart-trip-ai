"""External-data services with offline fallbacks."""
from datetime import timedelta
import os
import requests
from django.conf import settings
from django.db.models import Sum


def _fallback_forecast(destination, days=7):
    start = __import__('datetime').date.today()
    patterns = [
        ('Sunny', 30, 20), ('Partly cloudy', 29, 20), ('Sunny', 31, 21),
        ('Cloudy', 27, 20), ('Light rain', 26, 20), ('Sunny', 30, 20), ('Partly cloudy', 29, 20),
    ]
    result = []
    for i in range(max(1, int(days))):
        condition, high, low = patterns[i % len(patterns)]
        result.append({'date': start + timedelta(days=i), 'condition': condition,
                       'description': condition, 'temp_max': high, 'temp_min': low,
                       'humidity': 60 + (i * 3) % 25, 'wind_speed': 8 + i % 5,
                       'icon': ''})
    return result


def get_weather_forecast(destination, days=7):
    """Return normalized forecast records. Falls back to deterministic demo data."""
    key = getattr(settings, 'OPENWEATHER_API_KEY', '')
    if not key:
        return _fallback_forecast(destination, days)
    try:
        url = 'https://api.openweathermap.org/data/2.5/forecast'
        params = {'lat': destination.latitude, 'lon': destination.longitude, 'appid': key, 'units': 'metric'}
        response = requests.get(url, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
        grouped = {}
        for item in data.get('list', []):
            dt = __import__('datetime').datetime.fromtimestamp(item['dt']).date()
            grouped.setdefault(dt, []).append(item)
        result = []
        for day, entries in list(sorted(grouped.items()))[:days]:
            temps = [e['main']['temp'] for e in entries]
            sample = max(entries, key=lambda e: e['main']['temp'])
            weather = sample.get('weather', [{}])[0]
            result.append({'date': day, 'condition': weather.get('main', 'Unknown'),
                           'description': weather.get('description', '').title(),
                           'temp_max': round(max(temps), 1), 'temp_min': round(min(temps), 1),
                           'humidity': round(sum(e['main']['humidity'] for e in entries) / len(entries)),
                           'wind_speed': round(sum(e.get('wind', {}).get('speed', 0) for e in entries) / len(entries), 1),
                           'icon': weather.get('icon', '')})
        return result or _fallback_forecast(destination, days)
    except Exception:
        return _fallback_forecast(destination, days)


def get_currency_rates():
    """Return a small currency snapshot, using an offline fallback if needed."""
    fallback = {'INR': 1.0, 'USD': 0.012, 'EUR': 0.011, 'GBP': 0.0095, 'AED': 0.044}
    url = getattr(settings, 'CURRENCY_API_URL', '')
    if not url:
        return fallback
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        rates = response.json().get('rates', {})
        wanted = ['INR', 'USD', 'EUR', 'GBP', 'AED']
        return {code: rates.get(code, fallback[code]) for code in wanted}
    except Exception:
        return fallback


def compute_trip_score(trip, total_spent=0):
    """Return an explainable readiness score from budget, planning and group progress."""
    budget = float(trip.total_budget or 0)
    spent = float(total_spent or 0)
    budget_score = 100 if budget <= 0 else max(0, min(100, 100 - (spent / budget) * 100))
    itinerary_score = min(100, trip.itinerary_items.count() / max(trip.duration_days * 2, 1) * 100)
    checklist = list(trip.checklist_items.all())
    checklist_score = (sum(1 for i in checklist if i.completed) / len(checklist) * 100) if checklist else 100
    recommendation_score = 100 if trip.recommendations.exists() else 50
    breakdown = {
        'Budget headroom': round(budget_score),
        'Itinerary readiness': round(itinerary_score),
        'Checklist readiness': round(checklist_score),
        'Recommendations': round(recommendation_score),
    }
    score = round(sum(breakdown.values()) / len(breakdown))
    return score, breakdown


def assistant_reply(trip, message, total_spent, remaining):
    text = (message or '').strip().lower()
    if any(word in text for word in ('budget', 'spend', 'expense', 'money')):
        return 'Your trip budget is ₹{0:.2f}. You have ₹{1:.2f} remaining based on recorded expenses.'.format(float(trip.total_budget), float(remaining))
    if any(word in text for word in ('weather', 'rain', 'forecast')):
        forecast = get_weather_forecast(trip.destination, days=3)
        first = forecast[0] if forecast else None
        if first:
            return 'The fallback or live forecast starts with {0} on {1}, with a high of {2}°C and a low of {3}°C.'.format(first['condition'], first['date'].strftime('%d %b'), first['temp_max'], first['temp_min'])
    if any(word in text for word in ('itinerary', 'plan', 'places', 'visit')):
        count = trip.itinerary_items.count()
        return 'Your itinerary currently contains {0} activity entries across {1} day(s). Open the Itinerary section to generate or edit the plan.'.format(count, trip.duration_days)
    if 'hello' in text or 'hi' in text:
        return 'Hi. I am your SmartTrip assistant. Ask about your budget, weather, itinerary or trip progress.'
    return 'I can help with your budget, weather, itinerary and trip progress. Try asking, "How much budget do I have left?"'
