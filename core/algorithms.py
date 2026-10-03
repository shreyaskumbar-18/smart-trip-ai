"""Small, dependency-free travel algorithms used by SmartTrip AI."""
import heapq
import math
from itertools import permutations


def _distance(a, b):
    """Approximate great-circle distance in kilometres."""
    lat1, lon1 = a
    lat2, lon2 = b
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return r * 2 * math.asin(math.sqrt(max(0.0, min(1.0, h))))


def _route_distance(points, order):
    if len(order) < 2:
        return 0.0
    return sum(_distance(points[order[i]], points[order[i + 1]]) for i in range(len(order) - 1))


def tsp_optimize(points):
    """Return a route using exact search for small sets and nearest-neighbour + 2-opt otherwise."""
    points = list(points)
    n = len(points)
    original = list(range(n))
    if n <= 1:
        d = 0.0
        return {'original_order': original, 'optimized_order': original,
                'original_distance': d, 'optimized_distance': d, 'distance_saved': d}

    if n <= 8:
        best_order = original
        best_distance = float('inf')
        for order in permutations(range(n)):
            d = _route_distance(points, order)
            if d < best_distance:
                best_distance, best_order = d, list(order)
    else:
        remaining = set(range(1, n))
        best_order = [0]
        while remaining:
            current = best_order[-1]
            nxt = min(remaining, key=lambda i: _distance(points[current], points[i]))
            best_order.append(nxt)
            remaining.remove(nxt)
        improved = True
        while improved:
            improved = False
            for i in range(1, n - 2):
                for j in range(i + 1, n):
                    candidate = best_order[:i] + best_order[i:j][::-1] + best_order[j:]
                    if _route_distance(points, candidate) + 1e-9 < _route_distance(points, best_order):
                        best_order = candidate
                        improved = True

    original_distance = _route_distance(points, original)
    optimized_distance = _route_distance(points, best_order)
    return {
        'original_order': original,
        'optimized_order': best_order,
        'original_distance': round(original_distance, 3),
        'optimized_distance': round(optimized_distance, 3),
        'distance_saved': round(max(0.0, original_distance - optimized_distance), 3),
    }


def fractional_knapsack(items, capacity):
    """Select activity value inside a budget. Items need name, cost and value."""
    capacity = max(0.0, float(capacity))
    ranked = []
    for item in items:
        cost = max(0.0, float(item.get('cost', 0)))
        value = float(item.get('value', 0))
        if cost > 0:
            ranked.append((value / cost, item, cost, value))
    ranked.sort(key=lambda x: x[0], reverse=True)
    selected = []
    spent = 0.0
    value = 0.0
    for ratio, item, cost, item_value in ranked:
        if spent >= capacity:
            break
        fraction = min(1.0, (capacity - spent) / cost)
        selected.append({
            'name': item.get('name', 'Activity'),
            'category': item.get('category', ''),
            'cost': round(cost * fraction, 2),
            'value': round(item_value * fraction, 2),
            'fraction': round(fraction, 3),
        })
        spent += cost * fraction
        value += item_value * fraction
    return {'selected': selected, 'spent': round(spent, 2), 'value': round(value, 2),
            'capacity': round(capacity, 2), 'remaining': round(max(0.0, capacity - spent), 2)}


def dijkstra_shortest_path(points, start, end):
    """Build a 3-nearest-neighbour graph and find the shortest route."""
    points = list(points)
    n = len(points)
    if not (0 <= start < n and 0 <= end < n):
        return {'path': [], 'distance': 0.0}
    if start == end:
        return {'path': [start], 'distance': 0.0}
    graph = [[] for _ in range(n)]
    for i in range(n):
        neighbours = sorted((( _distance(points[i], points[j]), j) for j in range(n) if j != i), key=lambda x: x[0])[:3]
        for d, j in neighbours:
            graph[i].append((j, d))
            graph[j].append((i, d))
    dist = [float('inf')] * n
    prev = [None] * n
    dist[start] = 0.0
    heap = [(0.0, start)]
    while heap:
        current, node = heapq.heappop(heap)
        if current != dist[node]:
            continue
        if node == end:
            break
        for nxt, weight in graph[node]:
            new = current + weight
            if new < dist[nxt]:
                dist[nxt] = new
                prev[nxt] = node
                heapq.heappush(heap, (new, nxt))
    if math.isinf(dist[end]):
        return {'path': [], 'distance': 0.0}
    path = []
    node = end
    while node is not None:
        path.append(node)
        node = prev[node]
    path.reverse()
    return {'path': path, 'distance': round(dist[end], 3)}


def kmeans_cluster(points, k, iterations=20):
    """Deterministic lightweight K-Means returning lists of point indices."""
    points = list(points)
    n = len(points)
    k = max(1, min(int(k or 1), n)) if n else 0
    if not n:
        return []
    if k == 1:
        return [list(range(n))]
    centers = [points[int(round(i * (n - 1) / (k - 1)))] for i in range(k)]
    assignments = [0] * n
    for _ in range(iterations):
        changed = False
        for i, p in enumerate(points):
            nearest = min(range(k), key=lambda c: (p[0] - centers[c][0]) ** 2 + (p[1] - centers[c][1]) ** 2)
            if assignments[i] != nearest:
                assignments[i] = nearest
                changed = True
        new_centers = []
        for c in range(k):
            members = [points[i] for i in range(n) if assignments[i] == c]
            new_centers.append((sum(p[0] for p in members) / len(members), sum(p[1] for p in members) / len(members)) if members else centers[c])
        if not changed:
            break
        centers = new_centers
    clusters = [[] for _ in range(k)]
    for i, c in enumerate(assignments):
        clusters[c].append(i)
    return clusters


def weather_suitability(condition, temp_max, outdoor=True):
    """Return a 0-100 weather suitability score."""
    condition = (condition or '').lower()
    temp = float(temp_max or 0)
    score = 80.0
    if any(word in condition for word in ('thunder', 'storm')):
        score -= 55
    elif 'rain' in condition or 'shower' in condition:
        score -= 30 if outdoor else 5
    elif 'cloud' in condition:
        score -= 8 if outdoor else 0
    elif 'snow' in condition:
        score -= 45 if outdoor else 5
    if temp < 10:
        score -= 20 if outdoor else 5
    elif temp < 16:
        score -= 8 if outdoor else 0
    elif temp > 38:
        score -= 25 if outdoor else 3
    elif temp > 33:
        score -= 10 if outdoor else 0
    return int(max(0, min(100, round(score))))


def settle_expenses(net_map):
    """Greedy minimum-cash-flow settlement from net balances."""
    creditors = [[name, round(float(amount), 2)] for name, amount in net_map.items() if float(amount) > 0.009]
    debtors = [[name, round(-float(amount), 2)] for name, amount in net_map.items() if float(amount) < -0.009]
    settlements = []
    i = j = 0
    while i < len(debtors) and j < len(creditors):
        debtor, owed = debtors[i]
        creditor, due = creditors[j]
        amount = round(min(owed, due), 2)
        if amount > 0:
            settlements.append({'from': debtor, 'to': creditor, 'amount': amount})
        debtors[i][1] = round(owed - amount, 2)
        creditors[j][1] = round(due - amount, 2)
        if debtors[i][1] <= 0.009:
            i += 1
        if creditors[j][1] <= 0.009:
            j += 1
    return settlements
