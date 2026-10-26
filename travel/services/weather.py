"""Live Open-Meteo weather with a clearly labelled offline demonstration fallback."""
import json
from datetime import date
from functools import lru_cache
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError


def demo_forecast(day_number):
    patterns = [
        ("Clear", "Good for outdoor activities"),
        ("Cloudy", "Suitable for most activities"),
        ("Rain", "Prefer indoor attractions"),
        ("Clear", "Good for outdoor activities"),
        ("Cloudy", "Suitable for most activities"),
        ("Rain", "Prefer indoor attractions"),
        ("Clear", "Good for outdoor activities"),
    ]
    return patterns[(max(1, int(day_number)) - 1) % len(patterns)]


def weather_category_preferences(condition):
    condition = (condition or "").strip().lower()
    if condition in {"rain", "showers", "thunderstorm", "snow"}:
        return {"culture", "history", "food", "shopping"}
    if condition == "cloudy":
        return {"culture", "history", "nature", "adventure", "food", "shopping"}
    return {"nature", "adventure", "relaxation"}


KNOWN_COORDINATES = {
    "goa": (15.2993, 74.1240),
    "jaipur": (26.9124, 75.7873),
    "mumbai": (19.0760, 72.8777),
    "delhi": (28.6139, 77.2090),
    "kerala": (10.8505, 76.2711),
    "manali": (32.2432, 77.1892),
    "shimla": (31.1048, 77.1734),
    "agra": (27.1767, 78.0081),
    "varanasi": (25.3176, 82.9739),
    "udaipur": (24.5854, 73.7125),
    "bengaluru": (12.9716, 77.5946),
    "bangalore": (12.9716, 77.5946),
    "chennai": (13.0827, 80.2707),
    "kolkata": (22.5726, 88.3639),
    "ladakh": (34.1526, 77.5771),
    "leh": (34.1526, 77.5771),
    "rishikesh": (30.0869, 78.2676),
    "amritsar": (31.6340, 74.8723),
    "ooty": (11.4102, 76.6950),
    "darjeeling": (27.0410, 88.2663),
}


def _coordinates(destination):
    if destination is None:
        return None
    points = list(destination.attractions.exclude(latitude__isnull=True).exclude(longitude__isnull=True).values_list("latitude", "longitude")[:30])
    if points:
        return (sum(float(p[0]) for p in points) / len(points), sum(float(p[1]) for p in points) / len(points))
    name = (getattr(destination, "name", "") or "").lower().strip()
    state = (getattr(destination, "state", "") or "").lower().strip()
    for key, coords in KNOWN_COORDINATES.items():
        if key in name or key in state:
            return coords
    return None


def _condition_from_code(code):
    code = int(code or 0)
    if code == 0:
        return "Clear"
    if code in {1, 2, 3}:
        return "Cloudy" if code >= 2 else "Mostly clear"
    if code in {45, 48}:
        return "Fog"
    if code in {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82}:
        return "Rain"
    if code in {71, 73, 75, 77, 85, 86}:
        return "Snow"
    if code in {95, 96, 99}:
        return "Thunderstorm"
    return "Cloudy"


@lru_cache(maxsize=64)
def _fetch_forecast(latitude, longitude):
    params = urlencode({
        "latitude": latitude, "longitude": longitude,
        "current": "temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "forecast_days": 16, "timezone": "auto",
    })
    request = Request("https://api.open-meteo.com/v1/forecast?" + params, headers={"User-Agent": "SmartTripAI/1.0"})
    try:
        with urlopen(request, timeout=4) as response:
            return json.loads(response.read().decode("utf-8"))
    except (URLError, HTTPError, TimeoutError, ValueError, OSError):
        return None


def _live_forecast(destination, trip_date=None):
    coords = _coordinates(destination)
    if not coords:
        return None
    data = _fetch_forecast(round(coords[0], 4), round(coords[1], 4))
    if not data:
        return None
    current = data.get("current", {})
    daily = data.get("daily", {})
    target = trip_date.isoformat() if hasattr(trip_date, "isoformat") else str(trip_date or date.today().isoformat())
    dates = daily.get("time", [])
    if target in dates:
        idx = dates.index(target)
        condition = _condition_from_code((daily.get("weather_code") or [0])[idx])
        high = (daily.get("temperature_2m_max") or [None])[idx]
        low = (daily.get("temperature_2m_min") or [None])[idx]
        rain = (daily.get("precipitation_probability_max") or [None])[idx]
        advice = "Prefer indoor attractions and keep a flexible route." if condition in {"Rain", "Thunderstorm", "Snow"} else "Check local conditions before departure and follow your planned route."
        return {"condition": condition, "advice": advice, "source": "Open-Meteo forecast", "temperature": current.get("temperature_2m"), "high": high, "low": low, "rain_probability": rain, "wind": current.get("wind_speed_10m"), "target_date": target}
    condition = _condition_from_code(current.get("weather_code", 0))
    return {"condition": condition, "advice": "The requested date is outside the available forecast window. Current conditions are shown; check again closer to departure.", "source": "Open-Meteo current conditions", "temperature": current.get("temperature_2m"), "high": None, "low": None, "rain_probability": None, "wind": current.get("wind_speed_10m"), "target_date": target}


def weather_context(day_number, destination=None, trip_date=None):
    """Return weather data. The deterministic fallback is labelled and never presented as live."""
    live = _live_forecast(destination, trip_date) if destination is not None else None
    if live:
        return live
    condition, advice = demo_forecast(day_number)
    return {"condition": condition, "advice": advice + " (offline demo forecast)", "source": "Offline demo", "temperature": None, "high": None, "low": None, "rain_probability": None, "wind": None, "target_date": str(trip_date or "")}


def alternative_for(attractions, day_number, exclude_ids=None, current_attraction_id=None, condition=None):
    """Select a weather-compatible alternative using sustainability, hidden-gem and crowd signals."""
    exclude_ids = set(exclude_ids or [])
    condition = condition or demo_forecast(day_number)[0]
    if current_attraction_id is not None:
        exclude_ids.add(current_attraction_id)
    available = [a for a in attractions if a.id not in exclude_ids]
    if not available:
        return None
    preferred_categories = weather_category_preferences(condition)
    candidates = [a for a in available if (a.category or "").strip().lower() in preferred_categories]
    if not candidates:
        candidates = available
    def score(attraction):
        return (float(attraction.sustainability_score or 0) * 0.40 + float(attraction.hidden_gem_score or 0) * 0.35 + (100 - float(attraction.crowd_level or 0)) * 0.25)
    return max(candidates, key=score)
