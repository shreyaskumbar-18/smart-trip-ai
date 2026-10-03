from collections import defaultdict


def cluster_attractions(attractions):
    """
    Group attractions into simple POI clusters by category.

    The project stores category labels rather than a full GIS clustering
    dependency, so this deterministic clustering works offline and remains
    explainable for a college demonstration.
    """
    clusters = defaultdict(list)

    for attraction in attractions:
        category = (attraction.category or "other").strip().lower()
        clusters[category].append(attraction)

    return dict(clusters)


def cluster_summary(attractions):
    clusters = cluster_attractions(attractions)
    return {
        category: {
            "count": len(items),
            "attractions": [item.name for item in items],
        }
        for category, items in clusters.items()
    }
