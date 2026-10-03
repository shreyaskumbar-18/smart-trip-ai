def demo_forecast(day_number):
    """
    Return a deterministic demo forecast.

    The offline demo keeps SmartTrip fully usable without an API key.
    """

    patterns = [
        ("Clear", "Good for outdoor activities"),
        ("Cloudy", "Suitable for most activities"),
        ("Rain", "Prefer indoor attractions"),
        ("Clear", "Good for outdoor activities"),
        ("Cloudy", "Suitable for most activities"),
        ("Rain", "Prefer indoor attractions"),
        ("Clear", "Good for outdoor activities"),
    ]

    return patterns[(day_number - 1) % len(patterns)]


def weather_category_preferences(condition):
    condition = (condition or "").strip().lower()

    if condition == "rain":
        return {"culture", "history", "food", "shopping"}

    if condition == "cloudy":
        return {
            "culture",
            "history",
            "nature",
            "adventure",
            "food",
            "shopping",
        }

    return {"nature", "adventure", "relaxation"}


def alternative_for(
    attractions,
    day_number,
    exclude_ids=None,
    current_attraction_id=None,
):
    """
    Select the highest-scoring weather-compatible alternative.
    """

    exclude_ids = set(exclude_ids or [])
    condition, advice = demo_forecast(day_number)

    if current_attraction_id is not None:
        exclude_ids.add(current_attraction_id)

    available = [
        attraction
        for attraction in attractions
        if attraction.id not in exclude_ids
    ]

    if not available:
        return None

    preferred_categories = weather_category_preferences(condition)

    candidates = [
        attraction
        for attraction in available
        if (
            attraction.category
            and attraction.category.strip().lower()
            in preferred_categories
        )
    ]

    if not candidates:
        return None

    def alternative_score(attraction):
        sustainability = float(attraction.sustainability_score or 0)
        hidden_gem = float(attraction.hidden_gem_score or 0)
        crowd = float(attraction.crowd_level or 0)

        return (
            sustainability * 0.40
            + hidden_gem * 0.35
            + (100 - crowd) * 0.25
        )

    return max(candidates, key=alternative_score)


def weather_context(day_number):
    condition, advice = demo_forecast(day_number)
    return {
        "condition": condition,
        "advice": advice,
    }
