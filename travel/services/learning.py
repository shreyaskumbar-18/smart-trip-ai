from collections import Counter
from travel.models import RecommendationFeedback

def learned_interests(user):
    likes=RecommendationFeedback.objects.filter(user=user,action__in=["like","save"]).select_related("attraction")
    counts=Counter(x.attraction.category.lower() for x in likes)
    return [x[0] for x in counts.most_common(5)]

def preference_summary(user):
    interests=learned_interests(user)
    profile=getattr(user,"profile",None)
    declared=(profile.interests.split(",") if profile and profile.interests else [])
    merged=[]
    for x in declared+interests:
        x=x.strip().lower()
        if x and x not in merged: merged.append(x)
    return merged[:8]
