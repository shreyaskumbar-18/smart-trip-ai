from .learning import get_preferences, preference_summary


def interest_score(attraction, interest):
    text = f"{attraction.category} {attraction.tags} {attraction.description}".lower()
    if not interest:
        return 8
    return 35 if interest.lower() in text else 8


def recommendation_score(attraction, trip, feedback_ids=None):
    feedback_ids = set(feedback_ids or [])
    score = interest_score(attraction, getattr(trip, "interest", ""))
    user = getattr(trip, "user", None)
    try:
        learned = preference_summary(user) if user else []
        pref = get_preferences(user) if user else None
    except Exception:
        learned, pref = [], None

    text = f"{attraction.category} {attraction.tags} {attraction.description}".lower()
    category = (attraction.category or "").lower()

    if pref and hasattr(pref, category):
        score += float(getattr(pref, category)) * 18

    if learned and any(i in text for i in learned if i):
        score += 10

    score += float(attraction.sustainability_score or 0) * float(getattr(trip, "sustainability_priority", 3)) / 10
    if getattr(trip, "include_hidden_gems", False):
        score += float(attraction.hidden_gem_score or 0) / 5
    if pref:
        score += float(attraction.hidden_gem_score or 0) * pref.hidden_gems * 0.08
        score += float(attraction.sustainability_score or 0) * pref.sustainability * 0.05
    score += max(0, 100 - float(attraction.crowd_level or 0)) / 10

    # 1. Pace adjustment
    pace = (getattr(trip, "pace", "") or "").lower()
    duration = float(getattr(attraction, "duration", 2.0) or 2.0)
    if pace == "relaxed":
        if duration <= 2.0:
            score += 8
        elif duration > 3.5:
            score -= 6
        if any(w in text for w in ["scenic", "viewpoint", "beach", "park", "garden", "nature", "cafe"]):
            score += 5
    elif pace == "packed":
        if duration >= 1.5:
            score += 6

    # 2. Budget intelligence
    budget = float(getattr(trip, "budget", 0) or 0)
    days = max(1, int(getattr(trip, "days", 1) or 1))
    cost = float(getattr(attraction, "estimated_cost", 0) or 0)
    if budget > 0:
        daily_budget = budget / days
        if cost == 0:
            score += 10 if daily_budget < 2500 else 5
        elif cost > (daily_budget * 0.5):
            score -= 10
        elif cost <= (daily_budget * 0.2):
            score += 5

    # 3. Trip history personalization
    if user and hasattr(user, "trips"):
        try:
            past_interests = list(
                user.trips.exclude(id=getattr(trip, "id", None))
                .values_list("interest", flat=True)
            )
            if past_interests and any(pi and pi.lower() in text for pi in past_interests):
                score += 7
        except Exception:
            pass

    if attraction.id in feedback_ids:
        score += 12

    disliked_ids = getattr(trip, "_disliked_attraction_ids", set())
    if attraction.id in disliked_ids:
        score -= 18

    return round(max(0, min(100, score)), 2)


def explain(attraction, trip, score):
    reasons = []
    interest = getattr(trip, "interest", "") or ""
    category = getattr(attraction, "category", "") or ""
    tags = getattr(attraction, "tags", "") or ""
    text = f"{category} {tags}".lower()
    user = getattr(trip, "user", None)

    if interest and interest.lower() in text:
        reasons.append(f"matches your {interest} interest")

    try:
        learned = preference_summary(user) if user else []
        pref = get_preferences(user) if user else None
    except Exception:
        learned, pref = [], None

    if learned and any(i in text for i in learned if i):
        reasons.append("matches preferences learned from your activity")
    if pref and hasattr(pref, category.lower()) and getattr(pref, category.lower()) >= 0.65:
        reasons.append(f"your learned {category} preference is high")

    pace = (getattr(trip, "pace", "") or "").lower()
    duration = float(getattr(attraction, "duration", 2.0) or 2.0)
    if pace == "relaxed" and duration <= 2.0:
        reasons.append(f"fits your relaxed pace ({duration:g}h visit)")
    elif pace == "packed":
        reasons.append("fits your active, packed schedule")

    budget = float(getattr(trip, "budget", 0) or 0)
    cost = float(getattr(attraction, "estimated_cost", 0) or 0)
    if cost == 0:
        reasons.append("free admission fits budget-conscious travel")
    elif budget > 0 and cost <= ((budget / max(1, int(getattr(trip, "days", 1) or 1))) * 0.2):
        reasons.append(f"economical cost (₹{int(cost)})")

    if user and hasattr(user, "trips"):
        try:
            past_interests = list(
                user.trips.exclude(id=getattr(trip, "id", None))
                .values_list("interest", flat=True)
            )
            for pi in past_interests:
                if pi and pi.lower() in text:
                    reasons.append(f"aligns with your past trip interest in {pi}")
                    break
        except Exception:
            pass

    if attraction.hidden_gem_score >= 70 and getattr(trip, "include_hidden_gems", False):
        reasons.append("has strong hidden-gem potential")
    if attraction.sustainability_score >= 75:
        reasons.append("has a high sustainability score")
    if attraction.crowd_level <= 35:
        reasons.append("has lower crowd pressure")

    if not reasons:
        reasons.append("provides a good overall match for your trip preferences")

    return "Recommended because " + ", ".join(reasons) + f". Recommendation score: {score:.1f}/100."
