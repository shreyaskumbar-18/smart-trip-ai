"""Graph-based route algorithms for SmartTrip AI.

Distances are great-circle estimates in kilometres. They are not road distances
or live travel times. A road-routing provider should supply edge weights when
real routing data is configured.
"""
from __future__ import annotations

import heapq
from math import asin, cos, isfinite, radians, sin, sqrt


def haversine_km(a, b):
    """Great-circle distance between objects/dicts with latitude and longitude."""
    def coordinate(obj, key):
        if isinstance(obj, dict):
            return obj.get(key)
        return getattr(obj, key, None)

    values = [coordinate(obj, key) for obj, key in ((a, "latitude"), (a, "longitude"), (b, "latitude"), (b, "longitude"))]
    if any(value is None for value in values):
        return None
    lat1, lon1, lat2, lon2 = map(float, values)
    if not (-90 <= lat1 <= 90 and -90 <= lat2 <= 90 and -180 <= lon1 <= 180 and -180 <= lon2 <= 180):
        return None
    lat1, lon1, lat2, lon2 = map(radians, (lat1, lon1, lat2, lon2))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 6371.0 * 2 * asin(min(1.0, sqrt(h)))


def dijkstra(graph, start, goal):
    """Return (path, cost) for a weighted adjacency mapping, or ([], inf)."""
    if start not in graph or goal not in graph:
        return [], float("inf")
    distances = {node: float("inf") for node in graph}
    previous = {}
    distances[start] = 0.0
    queue = [(0.0, start)]
    while queue:
        cost, node = heapq.heappop(queue)
        if cost != distances[node]:
            continue
        if node == goal:
            break
        for neighbor, weight in graph.get(node, {}).items():
            weight = float(weight)
            if not isfinite(weight) or weight < 0:
                raise ValueError("Dijkstra requires finite, non-negative edge weights")
            candidate = cost + weight
            if candidate < distances.get(neighbor, float("inf")):
                distances[neighbor] = candidate
                previous[neighbor] = node
                if neighbor not in distances:
                    distances[neighbor] = candidate
                heapq.heappush(queue, (candidate, neighbor))
    if distances.get(goal, float("inf")) == float("inf"):
        return [], float("inf")
    path, current = [goal], goal
    while current != start:
        current = previous[current]
        path.append(current)
    path.reverse()
    return path, distances[goal]


def a_star(graph, coordinates, start, goal):
    """A* shortest path; coordinates maps node IDs to lat/lon objects or dicts."""
    if start not in graph or goal not in graph:
        return [], float("inf")

    def heuristic(node):
        distance = haversine_km(coordinates.get(node), coordinates.get(goal))
        return distance if distance is not None else 0.0

    costs = {start: 0.0}
    previous = {}
    queue = [(heuristic(start), 0.0, start)]
    while queue:
        _, cost, node = heapq.heappop(queue)
        if cost != costs.get(node):
            continue
        if node == goal:
            break
        for neighbor, weight in graph.get(node, {}).items():
            weight = float(weight)
            if not isfinite(weight) or weight < 0:
                raise ValueError("A* requires finite, non-negative edge weights")
            candidate = cost + weight
            if candidate < costs.get(neighbor, float("inf")):
                costs[neighbor] = candidate
                previous[neighbor] = node
                heapq.heappush(queue, (candidate + heuristic(neighbor), candidate, neighbor))
    if goal not in costs:
        return [], float("inf")
    path, current = [goal], goal
    while current != start:
        current = previous[current]
        path.append(current)
    path.reverse()
    return path, costs[goal]


def route_distance(route, distance_fn):
    route = list(route)
    total = 0.0
    for index in range(len(route) - 1):
        segment = distance_fn(route[index], route[index + 1])
        if segment is None:
            return None
        total += float(segment)
    return total


def nearest_neighbor_two_opt(items, distance_fn=haversine_km):
    """Build a nearest-neighbour tour and improve it with 2-opt local search."""
    remaining = list(items)
    # Missing coordinates are not free zero-distance edges. Optimize the
    # geocoded subset only, then preserve unlocated stops at the end.
    located = [item for item in remaining if distance_fn(item, item) is not None]
    unlocated = [item for item in remaining if distance_fn(item, item) is None]
    if unlocated:
        if len(located) < 3:
            return remaining
        remaining = located
    if len(remaining) < 3:
        return remaining
    route = [remaining.pop(0)]
    while remaining:
        current = route[-1]
        route.append(min(remaining, key=lambda item: distance_fn(current, item) if distance_fn(current, item) is not None else float("inf")))
        remaining.remove(route[-1])

    improved = True
    passes = 0
    while improved and passes < 25:
        improved = False
        passes += 1
        for i in range(1, len(route) - 2):
            for j in range(i + 1, len(route)):
                if j - i == 1:
                    continue
                before = (distance_fn(route[i - 1], route[i]) or 0.0) + (distance_fn(route[j - 1], route[j]) or 0.0)
                after = (distance_fn(route[i - 1], route[j - 1]) or 0.0) + (distance_fn(route[i], route[j]) or 0.0)
                if after + 1e-9 < before:
                    route[i:j] = reversed(route[i:j])
                    improved = True
    return route + unlocated


def build_geographic_graph(attractions, neighbors=4, max_edge_km=25.0):
    """Build an undirected proximity graph from attractions with coordinates."""
    points = {
        getattr(item, "id", index): item
        for index, item in enumerate(attractions)
        if getattr(item, "latitude", None) is not None and getattr(item, "longitude", None) is not None
    }
    graph = {node_id: {} for node_id in points}
    for node_id, point in points.items():
        candidates = []
        for other_id, other in points.items():
            if node_id == other_id:
                continue
            distance = haversine_km(point, other)
            if distance is not None and distance <= max_edge_km:
                candidates.append((distance, other_id))
        for distance, other_id in sorted(candidates)[:max(1, neighbors)]:
            graph[node_id][other_id] = distance
            graph[other_id][node_id] = min(graph[other_id].get(node_id, float("inf")), distance)
    return graph, points


def plan_geographic_path(attractions, start_id, goal_id, algorithm="astar", neighbors=4, max_edge_km=25.0):
    """Find a path through the POI proximity graph using A* or Dijkstra."""
    graph, points = build_geographic_graph(attractions, neighbors=neighbors, max_edge_km=max_edge_km)
    if algorithm.lower() == "dijkstra":
        path, cost = dijkstra(graph, start_id, goal_id)
    else:
        path, cost = a_star(graph, points, start_id, goal_id)
    by_id = {getattr(item, "id", index): item for index, item in enumerate(attractions)}
    return {"algorithm": "Dijkstra" if algorithm.lower() == "dijkstra" else "A*", "path_ids": path, "attractions": [by_id[node_id] for node_id in path if node_id in by_id], "distance_km": round(cost, 2) if cost != float("inf") else None, "is_estimate": True}
