"""Explainable point-of-interest clustering.

Uses dependency-free DBSCAN over geographic coordinates when enough attractions
have coordinates. Missing-coordinate records are grouped by category. When there
are too few coordinates, category grouping is used as an explicit fallback.
"""
from collections import defaultdict
from .route_algorithms import haversine_km


def _dbscan(points, eps_km=5.0, min_samples=2):
    labels = {}
    cluster_id = 0

    def neighbors(point_id):
        point = points[point_id]
        found = []
        for other_id, other in points.items():
            distance = haversine_km(point, other)
            if distance is not None and distance <= eps_km:
                found.append(other_id)
        return found

    visited = set()
    for point_id in points:
        if point_id in visited:
            continue
        visited.add(point_id)
        nearby = neighbors(point_id)
        if len(nearby) < min_samples:
            labels[point_id] = -1
            continue
        labels[point_id] = cluster_id
        queue = list(nearby)
        queued = set(queue)
        while queue:
            candidate = queue.pop(0)
            if candidate not in visited:
                visited.add(candidate)
                candidate_neighbors = neighbors(candidate)
                if len(candidate_neighbors) >= min_samples:
                    for neighbor_id in candidate_neighbors:
                        if neighbor_id not in queued:
                            queue.append(neighbor_id)
                            queued.add(neighbor_id)
            if labels.get(candidate) in (None, -1):
                labels[candidate] = cluster_id
        cluster_id += 1
    return labels


def cluster_attractions(attractions, eps_km=5.0, min_samples=2):
    """Return groups by nearby geography, with a category fallback."""
    attractions = list(attractions)
    points = {
        item.id: item for item in attractions
        if getattr(item, "latitude", None) is not None and getattr(item, "longitude", None) is not None
    }
    if len(points) >= min_samples:
        labels = _dbscan(points, eps_km=eps_km, min_samples=min_samples)
        clusters = defaultdict(list)
        for item_id, label in labels.items():
            name = f"Nearby area {label + 1}" if label >= 0 else "Geographic outliers"
            clusters[name].append(points[item_id])
        # Attractions without coordinates cannot be placed on a map, so keep them discoverable by category.
        missing = [item for item in attractions if item.id not in points]
        for item in missing:
            category = (item.category or "other").strip().lower()
            clusters[f"Unmapped · {category}"].append(item)
        return dict(clusters)

    clusters = defaultdict(list)
    for item in attractions:
        category = (item.category or "other").strip().lower()
        clusters[f"Category · {category}"].append(item)
    return dict(clusters)


def cluster_summary(attractions, eps_km=5.0, min_samples=2):
    clusters = cluster_attractions(attractions, eps_km=eps_km, min_samples=min_samples)
    return {
        cluster_name: {
            "count": len(items),
            "attractions": [item.name for item in items],
        }
        for cluster_name, items in clusters.items()
    }
