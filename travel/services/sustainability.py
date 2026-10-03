def trip_sustainability(trip):
    items=list(trip.items.select_related("attraction"))
    if not items: return 0
    return round(sum(i.attraction.sustainability_score for i in items)/len(items),1)
