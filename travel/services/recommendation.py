from .learning import preference_summary


def interest_score(attraction, interest):
    text = (
        f"{attraction.category} "
        f"{attraction.tags} "
        f"{attraction.description}"
    ).lower()

    if not interest:
        return 8

    return 35 if interest.lower() in text else 8


def recommendation_score(attraction, trip, feedback_ids=None):
    """
    Explainable recommendation score on a 0-100 scale.

    Signals:
    - declared trip interest
    - learned user interests
    - sustainability priority
    - hidden-gem preference
    - crowd pressure
    - explicit likes/dislikes
    """

    feedback_ids = set(feedback_ids or [])

    score = interest_score(
        attraction,
        getattr(trip, "interest", ""),
    )

    # Learned preferences from previous feedback/profile data.
    try:
        learned = preference_summary(trip.user)
    except Exception:
        learned = []

    attraction_text = (
        f"{attraction.category} "
        f"{attraction.tags} "
        f"{attraction.description}"
    ).lower()

    if learned and any(
        interest in attraction_text
        for interest in learned
        if interest
    ):
        score += 10

    score += (
        float(attraction.sustainability_score or 0)
        * float(getattr(trip, "sustainability_priority", 3))
        / 10
    )

    if getattr(trip, "include_hidden_gems", False):
        score += float(attraction.hidden_gem_score or 0) / 5

    score += (
        max(0, 100 - float(attraction.crowd_level or 0))
        / 10
    )

    if attraction.id in feedback_ids:
        score += 12

    # Cache explicit dislikes for the current request.
    disliked_ids = getattr(trip, "_disliked_attraction_ids", set())
    if attraction.id in disliked_ids:
        score -= 18

    return round(
        max(0, min(100, score)),
        2,
    )


def explain(attraction, trip, score):
    reasons = []

    interest = getattr(trip, "interest", "") or ""
    category = getattr(attraction, "category", "") or ""
    tags = getattr(attraction, "tags", "") or ""

    attraction_text = (
        category
        + " "
        + tags
    ).lower()

    if interest and interest.lower() in attraction_text:
        reasons.append(
            f"it matches your {interest} interest"
        )

    try:
        learned = preference_summary(trip.user)
    except Exception:
        learned = []

    if learned and any(
        interest in attraction_text
        for interest in learned
        if interest
    ):
        reasons.append(
            "it matches preferences learned from your activity"
        )

    if (
        attraction.hidden_gem_score >= 70
        and getattr(trip, "include_hidden_gems", False)
    ):
        reasons.append(
            "it has strong hidden-gem potential"
        )

    if attraction.sustainability_score >= 75:
        reasons.append(
            "it has a high sustainability score"
        )

    if attraction.crowd_level <= 35:
        reasons.append(
            "it has lower crowd pressure"
        )

    if not reasons:
        reasons.append(
            "it provides a good overall match "
            "for your trip preferences"
        )

    return (
        "Recommended because "
        + ", ".join(reasons)
        + f". Recommendation score: {score:.1f}/100."
    )
