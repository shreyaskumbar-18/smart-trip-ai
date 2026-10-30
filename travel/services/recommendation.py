from .learning import get_preferences, preference_summary
from types import SimpleNamespace


def interest_score(attraction, interest):
    text = f"{attraction.category} {attraction.tags} {attraction.description}".lower()
    if not interest:
        return 8
    return 35 if interest.lower() in text else 8


def _recommendation_score_result(attraction, trip, feedback_ids=None, include_breakdown=False):
    feedback_ids = set(feedback_ids or [])
    score = interest_score(attraction, getattr(trip, "interest", ""))
    components = None
    if include_breakdown:
        components = [{"label": "Interest match baseline", "value": score}]

    def add_component(label, value):
        nonlocal score
        score += value
        if components is not None:
            components.append({"label": label, "value": value})

    user = getattr(trip, "user", None)
    group_users = list(getattr(trip, "_group_users", []) or [])
    try:
        if group_users:
            group_preferences = [get_preferences(member) for member in group_users]
            pref = SimpleNamespace(**{
                field: sum(float(getattr(item, field)) for item in group_preferences) / len(group_preferences)
                for field in ("culture", "nature", "adventure", "food", "history", "shopping", "relaxation", "hidden_gems", "sustainability")
            })
            learned = sorted({term for member in group_users for term in preference_summary(member)})
        else:
            learned = preference_summary(user) if user else []
            pref = get_preferences(user) if user else None
    except Exception:
        learned, pref = [], None

    text = f"{attraction.category} {attraction.tags} {attraction.description}".lower()
    category = (attraction.category or "").lower()

    if pref and hasattr(pref, category):
        add_component("Learned category preference", float(getattr(pref, category)) * 18)

    if learned and any(i in text for i in learned if i):
        add_component("Profile or feedback-derived interest match", 10)

    add_component(
        "Sustainability score weighted by trip priority",
        float(attraction.sustainability_score or 0) * float(getattr(trip, "sustainability_priority", 3)) / 10,
    )
    if getattr(trip, "include_hidden_gems", False):
        add_component("Hidden-gem score enabled for this trip", float(attraction.hidden_gem_score or 0) / 5)
    if pref:
        add_component(
            "Hidden-gem score weighted by learned preference",
            float(attraction.hidden_gem_score or 0) * pref.hidden_gems * 0.08,
        )
        add_component(
            "Sustainability score weighted by learned preference",
            float(attraction.sustainability_score or 0) * pref.sustainability * 0.05,
        )
    add_component("Lower-crowd factor", max(0, 100 - float(attraction.crowd_level or 0)) / 10)

    # 1. Pace adjustment
    pace = (getattr(trip, "pace", "") or "").lower()
    duration = float(getattr(attraction, "duration_hours", 2.0) or 2.0)
    if pace == "relaxed":
        if duration <= 2.0:
            add_component("Relaxed-pace duration fit", 8)
        elif duration > 3.5:
            add_component("Relaxed-pace long-stop adjustment", -6)
        if any(w in text for w in ["scenic", "viewpoint", "beach", "park", "garden", "nature", "cafe"]):
            add_component("Relaxed-pace setting fit", 5)
    elif pace == "packed":
        if duration >= 1.5:
            add_component("Packed-pace duration fit", 6)

    # 2. Budget intelligence
    budget = float(getattr(trip, "budget", 0) or 0)
    days = max(1, int(getattr(trip, "days", 1) or 1))
    cost = float(getattr(attraction, "estimated_cost", 0) or 0)
    if budget > 0:
        daily_budget = budget / (days * max(1, int(getattr(trip, "travelers", 1) or 1)))
        if cost == 0:
            add_component("Free-admission budget adjustment", 10 if daily_budget < 2500 else 5)
        elif cost > (daily_budget * 0.5):
            add_component("High entry-cost adjustment", -10)
        elif cost <= (daily_budget * 0.2):
            add_component("Low entry-cost adjustment", 5)

    # 3. Trip history personalization
    if group_users:
        try:
            past_interests = [
                interest for member in group_users
                for interest in member.trips.exclude(id=getattr(trip, "id", None)).values_list("interest", flat=True)
            ]
            if any(interest and interest.lower() in text for interest in past_interests):
                add_component("Group trip-history match", 7)
        except Exception:
            pass
    elif user and hasattr(user, "trips"):
        try:
            past_interests = list(
                user.trips.exclude(id=getattr(trip, "id", None))
                .values_list("interest", flat=True)
            )
            if past_interests and any(pi and pi.lower() in text for pi in past_interests):
                add_component("Trip-history match", 7)
        except Exception:
            pass

    if attraction.id in feedback_ids:
        add_component("Positive attraction feedback", 12)

    disliked_ids = getattr(trip, "_disliked_attraction_ids", set())
    if attraction.id in disliked_ids:
        add_component("Negative attraction feedback", -18)

    final_score = round(max(0, min(100, score)), 2)
    if components is None:
        return final_score
    return {
        "score": final_score,
        "raw_score": score,
        "clamped": score < 0 or score > 100,
        "components": components,
    }


def recommendation_score(attraction, trip, feedback_ids=None):
    """Return the existing clamped and rounded recommendation score."""
    return _recommendation_score_result(attraction, trip, feedback_ids)


def recommendation_score_breakdown(attraction, trip, feedback_ids=None):
    """Return exact point adjustments from the same calculation as the score.

    The returned components are additive before the existing 0–100 clamp and
    two-decimal rounding. Signals are reported only when the scorer applies
    them; no separate explanation formula is used.
    """
    return _recommendation_score_result(attraction, trip, feedback_ids, include_breakdown=True)


def explain(attraction, trip, score, feedback_ids=None, concise=False):
    reasons = []
    interest = getattr(trip, "interest", "") or ""
    category = getattr(attraction, "category", "") or ""
    tags = getattr(attraction, "tags", "") or ""
    text = f"{category} {tags} {getattr(attraction, 'description', '')}".lower()
    user = getattr(trip, "user", None)

    if interest and interest.lower() in text:
        reasons.append(f"matches your {interest} interest")
    elif interest:
        reasons.append(f"the {interest} theme is one factor in its overall score")

    try:
        group_users = list(getattr(trip, "_group_users", []) or [])
        if group_users:
            learned = sorted({term for member in group_users for term in preference_summary(member)})
            group_preferences = [get_preferences(member) for member in group_users]
            pref_values = {
                field: sum(float(getattr(item, field)) for item in group_preferences) / len(group_preferences)
                for field in ("culture", "nature", "adventure", "food", "history", "shopping", "relaxation", "hidden_gems", "sustainability")
            }
            pref = SimpleNamespace(**pref_values)
        else:
            learned = preference_summary(user) if user else []
            pref = get_preferences(user) if user else None
    except Exception:
        learned, pref = [], None

    if learned and any(i in text for i in learned if i):
        reasons.append("matches preferences learned from your activity")
    preference_key = category.lower()
    if pref and hasattr(pref, preference_key):
        preference_value = float(getattr(pref, preference_key))
        if preference_value != 0.5:
            reasons.append(f"your learned {category} preference ({preference_value:.2f}) is included")

    pace = (getattr(trip, "pace", "") or "").lower()
    duration = float(getattr(attraction, "duration_hours", 2.0) or 2.0)
    if pace == "relaxed" and duration <= 2.0:
        reasons.append(f"fits your relaxed pace ({duration:g}h visit)")
    elif pace == "relaxed" and duration > 3.5:
        reasons.append(f"its {duration:g}h visit is a longer stop for your relaxed pace")
    elif pace == "packed":
        reasons.append("fits your active, packed schedule")

    budget = float(getattr(trip, "budget", 0) or 0)
    cost = float(getattr(attraction, "estimated_cost", 0) or 0)
    if cost == 0:
        reasons.append("free admission fits budget-conscious travel")
    elif budget > 0 and cost <= ((budget / (max(1, int(getattr(trip, "days", 1) or 1)) * max(1, int(getattr(trip, "travelers", 1) or 1)))) * 0.2):
        reasons.append(f"economical cost (₹{int(cost)})")
    elif budget > 0 and cost > ((budget / (max(1, int(getattr(trip, "days", 1) or 1)) * max(1, int(getattr(trip, "travelers", 1) or 1)))) * 0.5):
        reasons.append("its estimated entry cost is high against the daily per-traveler budget")

    group_users = list(getattr(trip, "_group_users", []) or [])
    history_match = False
    if group_users:
        try:
            past_interests = [
                item for member in group_users
                for item in member.trips.exclude(id=getattr(trip, "id", None)).values_list("interest", flat=True)
            ]
            history_match = any(item and item.lower() in text for item in past_interests)
            if history_match:
                reasons.append("matches a group member's past trip interests")
        except Exception:
            pass
    elif user and hasattr(user, "trips"):
        try:
            past_interests = list(
                user.trips.exclude(id=getattr(trip, "id", None))
                .values_list("interest", flat=True)
            )
            for pi in past_interests:
                if pi and pi.lower() in text:
                    history_match = True
                    reasons.append(f"aligns with your past trip interest in {pi}")
                    break
        except Exception:
            pass

    if attraction.hidden_gem_score >= 70 and getattr(trip, "include_hidden_gems", False):
        reasons.append("has strong hidden-gem potential")
    if float(getattr(trip, "sustainability_priority", 0) or 0) > 0:
        reasons.append(f"sustainability score {attraction.sustainability_score}/100 is weighted by your trip priority")
    if attraction.sustainability_score >= 75 and float(getattr(trip, "sustainability_priority", 0) or 0) > 0:
        reasons.append("has a high sustainability score")
    if attraction.crowd_level <= 35:
        reasons.append("has lower crowd pressure")
    else:
        reasons.append("crowd level is included in the score")
    if attraction.id in set(feedback_ids or []):
        reasons.append("you previously liked or saved this attraction")
    if attraction.id in getattr(trip, "_disliked_attraction_ids", set()):
        reasons.append("recorded feedback discourages this attraction")
    if getattr(trip, "_group_users", None):
        reasons.append("its score includes group member preferences")

    if concise:
        compact = []
        interest_match = bool(interest and interest.lower() in text)
        learned_match = bool(learned and any(term in text for term in learned if term))
        if interest:
            if interest_match:
                compact.append(f"matches your {interest} interest")
            else:
                compact.append(f"scored using your {interest} interest")
        if learned_match and not interest_match:
            compact.append("matches preferences learned from your activity")
        if history_match and not interest_match:
            compact.append("matches a past trip interest")

        preference_key = category.lower()
        if pref and hasattr(pref, preference_key):
            preference_value = float(getattr(pref, preference_key))
            if preference_value != 0.5 and not (interest and preference_key == interest.lower()):
                compact.append(f"your learned {preference_key} preference ({preference_value:.2f}) contributed")

        if pace == "relaxed" and duration <= 2.0:
            compact.append(f"fits your relaxed pace ({duration:g}h visit)")
        elif pace == "relaxed" and duration > 3.5:
            compact.append(f"its {duration:g}h visit is a longer stop for your relaxed pace")
        elif pace == "packed":
            compact.append("fits your packed schedule")

        daily_per_traveler = budget / (
            max(1, int(getattr(trip, "days", 1) or 1))
            * max(1, int(getattr(trip, "travelers", 1) or 1))
        ) if budget > 0 else 0
        if cost == 0:
            compact.append("free admission")
        elif budget > 0 and cost <= daily_per_traveler * 0.2:
            compact.append(f"estimated entry cost ₹{int(cost)} is low for the daily per-traveler budget")
        elif budget > 0 and cost > daily_per_traveler * 0.5:
            compact.append("estimated entry cost is high for the daily per-traveler budget")

        score_signals = []
        if float(getattr(trip, "sustainability_priority", 0) or 0) > 0:
            score_signals.append(f"sustainability {attraction.sustainability_score}/100")
        if getattr(trip, "include_hidden_gems", False) or pref:
            score_signals.append(f"hidden-gem score {attraction.hidden_gem_score}/100")
        score_signals.append(f"crowd level {attraction.crowd_level}/100")
        compact.append("score signals: " + ", ".join(score_signals))

        if attraction.id in set(feedback_ids or []):
            compact.append("your positive feedback contributed")
        if not compact:
            compact.append("the overall score balances available trip signals")
        reasons = compact[:5]

    if not reasons:
        reasons.append("the overall score balances the available trip preference signals")

    return "Recommended because " + ", ".join(reasons) + f". Recommendation score: {score:.1f}/100."
