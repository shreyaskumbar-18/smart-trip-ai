from collections import Counter
from django.db.models import Q
from travel.models import RecommendationFeedback, UserPreference


CATEGORIES = ["culture","nature","adventure","food","history","shopping","relaxation"]


def get_preferences(user):
    pref, _ = UserPreference.objects.get_or_create(user=user)
    return pref


def learned_interests(user):
    likes = RecommendationFeedback.objects.filter(
        user=user, action__in=["like","save"]
    ).select_related("attraction")
    counts = Counter(
        x.attraction.category.lower()
        for x in likes
        if x.attraction and x.attraction.category
    )
    return [x[0] for x in counts.most_common(5)]


def preference_summary(user):
    interests = learned_interests(user)
    profile = getattr(user, "profile", None)
    declared = profile.interests.split(",") if profile and profile.interests else []
    pref = get_preferences(user)
    learned = sorted(pref.as_dict().items(), key=lambda x: x[1], reverse=True)
    merged = []
    for x in declared + [k for k,v in learned if v >= 0.62] + interests:
        x = x.strip().lower()
        if x and x not in merged:
            merged.append(x)
    return merged[:8]


def update_preference_from_feedback(user, attraction, action):
    pref = get_preferences(user)
    category = (attraction.category or "").strip().lower()
    if category not in CATEGORIES:
        return pref

    delta = 0.08 if action in {"like","save"} else -0.08 if action == "dislike" else 0.0
    current = getattr(pref, category)
    setattr(pref, category, max(0.0, min(1.0, current + delta)))

    hidden = float(attraction.hidden_gem_score or 0) / 100
    sustain = float(attraction.sustainability_score or 0) / 100
    if action in {"like","save"}:
        pref.hidden_gems = max(0.0, min(1.0, pref.hidden_gems + (0.03 if hidden >= 0.7 else 0)))
        pref.sustainability = max(0.0, min(1.0, pref.sustainability + (0.03 if sustain >= 0.75 else 0)))
    pref.feedback_count += 1
    pref.save()
    return pref


def aggregate_group_preferences(members, minority_weight=0.30):
    """Aggregate member preferences while protecting minority interests.

    Each category receives 70% mean satisfaction and 30% minimum member
    satisfaction by default. This is a transparent fairness heuristic, not a
    guarantee that every member will be equally satisfied.
    """
    members = list(members)
    if not members:
        return {}
    category_values = Counter()
    category_members = {}
    for member in members:
        preferences = get_preferences(member).as_dict()
        for category, value in preferences.items():
            category_members.setdefault(category, []).append(float(value))
    for category, values in category_members.items():
        mean_value = sum(values) / len(values)
        minimum_value = min(values)
        category_values[category] = (1 - minority_weight) * mean_value + minority_weight * minimum_value
    return dict(sorted(category_values.items(), key=lambda item: (-item[1], item[0])))
