"""Dependency-free NSGA-II multi-objective itinerary optimizer.

This implementation uses a binary chromosome (one bit per attraction),
non-dominated sorting, crowding distance, tournament selection, uniform
crossover, bit-flip mutation, and constraint repair. It returns a Pareto set
of alternatives rather than pretending there is one universally best plan.
"""
from __future__ import annotations

import random
from math import asin, cos, radians, sin, sqrt

from .recommendation import recommendation_score, explain
from .route_algorithms import nearest_neighbor_two_opt


PACE_LIMIT = {"relaxed": 2, "balanced": 3, "packed": 4}


def _distance(a, b):
    if any(getattr(x, field, None) is None for x in (a, b) for field in ("latitude", "longitude")):
        return None
    lat1, lon1 = radians(float(a.latitude)), radians(float(a.longitude))
    lat2, lon2 = radians(float(b.latitude)), radians(float(b.longitude))
    if not (-radians(90) <= lat1 <= radians(90) and -radians(90) <= lat2 <= radians(90) and -radians(180) <= lon1 <= radians(180) and -radians(180) <= lon2 <= radians(180)):
        return None
    dlat, dlon = lat2 - lat1, lon2 - lon1
    hav = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 6371.0 * 2 * asin(min(1.0, sqrt(hav)))


def _route(attractions):
    """Nearest-neighbour route with a bounded 2-opt local-search improvement."""
    return nearest_neighbor_two_opt(list(attractions), _distance)


def _dominates(left, right):
    return all(a <= b for a, b in zip(left, right)) and any(a < b for a, b in zip(left, right))


def _fast_non_dominated_sort(population):
    dominates_set = {}
    dominated_by_count = {}
    fronts = [[]]
    for p in population:
        dominates_set[id(p)] = []
        dominated_by_count[id(p)] = 0
        for q in population:
            if p is q:
                continue
            if _dominates(p["fitness"], q["fitness"]):
                dominates_set[id(p)].append(q)
            elif _dominates(q["fitness"], p["fitness"]):
                dominated_by_count[id(p)] += 1
        if dominated_by_count[id(p)] == 0:
            p["rank"] = 0
            fronts[0].append(p)
    i = 0
    while i < len(fronts) and fronts[i]:
        next_front = []
        for p in fronts[i]:
            for q in dominates_set[id(p)]:
                dominated_by_count[id(q)] -= 1
                if dominated_by_count[id(q)] == 0:
                    q["rank"] = i + 1
                    next_front.append(q)
        if next_front:
            fronts.append(next_front)
        i += 1
    return fronts


def _crowding_distance(front):
    for item in front:
        item["crowding"] = 0.0
    if len(front) <= 2:
        for item in front:
            item["crowding"] = float("inf")
        return
    dimensions = len(front[0]["fitness"])
    for dim in range(dimensions):
        ordered = sorted(front, key=lambda item: item["fitness"][dim])
        ordered[0]["crowding"] = float("inf")
        ordered[-1]["crowding"] = float("inf")
        low = ordered[0]["fitness"][dim]
        high = ordered[-1]["fitness"][dim]
        if high == low:
            continue
        for i in range(1, len(ordered) - 1):
            if ordered[i]["crowding"] != float("inf"):
                ordered[i]["crowding"] += (ordered[i + 1]["fitness"][dim] - ordered[i - 1]["fitness"][dim]) / (high - low)


def _select_parent(population, rng):
    a, b = rng.sample(population, 2)
    if a["rank"] != b["rank"]:
        return a if a["rank"] < b["rank"] else b
    return a if a["crowding"] >= b["crowding"] else b


def optimize_pareto(trip, attractions, feedback_ids=None, population_size=48, generations=45, seed=42, alternatives=3):
    """Return Pareto-optimal itinerary options for a Trip and attraction list.

    Objectives: maximize recommendation match, maximize sustainability,
    minimize estimated cost, and minimize estimated inter-attraction distance.
    Budget and daily activity count are repaired as hard constraints.
    """
    rng = random.Random(seed)
    unique_attractions = []
    seen_ids = set()
    destination_id = getattr(trip, "destination_id", None)
    for attraction in attractions:
        attraction_id = getattr(attraction, "id", None)
        key = ("id", attraction_id) if attraction_id is not None else ("object", id(attraction))
        attraction_destination = getattr(attraction, "destination_id", None)
        if key in seen_ids or (destination_id is not None and attraction_destination is not None and attraction_destination != destination_id):
            continue
        seen_ids.add(key)
        unique_attractions.append(attraction)
    attractions = unique_attractions
    feedback_ids = set(feedback_ids or [])
    if not attractions or not getattr(trip, "days", 0):
        return []

    # Keep the input size practical while retaining high-value candidates.
    scored = [(recommendation_score(a, trip, feedback_ids), a) for a in attractions]
    scored.sort(key=lambda pair: pair[0], reverse=True)
    attractions = [a for _, a in scored[: min(36, len(scored))]]
    scores = {a.id: recommendation_score(a, trip, feedback_ids) for a in attractions}
    max_stops = max(1, min(len(attractions), trip.days * PACE_LIMIT.get(getattr(trip, "pace", "balanced"), 3)))
    budget = max(0, int(getattr(trip, "budget", 0) or 0))
    travelers = max(1, int(getattr(trip, "travelers", 1) or 1))

    def repair(bits):
        selected = [i for i, bit in enumerate(bits) if bit]
        # Cap daily pace first, dropping the weakest marginal choices.
        selected.sort(key=lambda i: scores[attractions[i].id], reverse=True)
        selected = selected[:max_stops]
        # Attraction costs are treated as per-traveler estimates.
        total = sum(int(attractions[i].estimated_cost or 0) for i in selected) * travelers
        while len(selected) > 1 and total > budget:
            drop = min(selected, key=lambda i: scores[attractions[i].id] / max(1, int(attractions[i].estimated_cost or 0)))
            selected.remove(drop)
            total = sum(int(attractions[i].estimated_cost or 0) for i in selected) * travelers
        if not selected:
            affordable = [i for i, a in enumerate(attractions) if int(a.estimated_cost or 0) * travelers <= budget]
            if affordable:
                selected = [max(affordable, key=lambda i: scores[attractions[i].id])]
            else:
                # An empty plan is more honest than silently violating the hard budget.
                selected = []
        selected_set = set(selected)
        return [1 if i in selected_set else 0 for i in range(len(attractions))]

    def evaluate(bits):
        chosen = [attractions[i] for i, bit in enumerate(bits) if bit]
        ordered = _route(chosen)
        pref = sum(scores[a.id] for a in ordered) / max(1, len(ordered))
        sustainability = sum(float(a.sustainability_score or 0) for a in ordered) / max(1, len(ordered))
        coverage = min(100.0, len(ordered) / max(1, max_stops) * 100.0)
        cost = sum(int(a.estimated_cost or 0) for a in ordered) * travelers
        edges = [_distance(ordered[i], ordered[i + 1]) for i in range(len(ordered) - 1)]
        missing_edges = sum(value is None for value in edges) + sum(
            any(getattr(attraction, field, None) is None for field in ("latitude", "longitude"))
            for attraction in ordered
        )
        distance = sum(value for value in edges if value is not None)
        # Minimize preference/sustainability deficits, cost and distance, while
        # maximizing useful itinerary coverage. This avoids favoring empty or
        # one-stop plans solely because they are cheap and have zero route length.
        fitness = (100.0 - pref, 100.0 - sustainability, float(cost), float(distance), 100.0 - coverage, float(missing_edges))
        return {"bits": bits, "fitness": fitness, "selected": ordered}

    population = []
    for _ in range(max(12, population_size)):
        bits = [1 if rng.random() < 0.42 else 0 for _ in attractions]
        population.append(evaluate(repair(bits)))
    mutation_rate = 1.0 / max(1, len(attractions))

    for _ in range(max(1, generations)):
        fronts = _fast_non_dominated_sort(population)
        for front in fronts:
            _crowding_distance(front)
        offspring = []
        while len(offspring) < len(population):
            p1 = _select_parent(population, rng)
            p2 = _select_parent(population, rng)
            c1, c2 = list(p1["bits"]), list(p2["bits"])
            if rng.random() < 0.9 and len(c1) > 1:
                for i in range(len(c1)):
                    if rng.random() < 0.5:
                        c1[i], c2[i] = c2[i], c1[i]
            for child in (c1, c2):
                for i in range(len(child)):
                    if rng.random() < mutation_rate:
                        child[i] = 1 - child[i]
                offspring.append(evaluate(repair(child)))
                if len(offspring) >= len(population):
                    break
        combined = population + offspring
        next_population = []
        for front in _fast_non_dominated_sort(combined):
            _crowding_distance(front)
            if len(next_population) + len(front) <= len(population):
                next_population.extend(front)
            else:
                front.sort(key=lambda item: item["crowding"], reverse=True)
                next_population.extend(front[: len(population) - len(next_population)])
                break
        population = next_population

    pareto = _fast_non_dominated_sort(population)[0]
    # Keep only non-empty, budget-feasible candidates before presenting alternatives.
    pareto = [item for item in pareto if item["selected"] and item["fitness"][2] <= budget]
    # Deduplicate alternatives by selected attraction IDs.
    unique = {}
    for item in pareto:
        key = tuple(sorted(a.id for a in item["selected"]))
        unique.setdefault(key, item)
    options = list(unique.values())
    if not options:
        return []

    # Select plans with useful coverage first, while retaining Pareto diversity.
    _crowding_distance(options)
    options.sort(key=lambda item: (len(item["selected"]), item["crowding"]), reverse=True)
    chosen_options = options[: max(1, alternatives)]
    result = []
    for index, item in enumerate(chosen_options, 1):
        ordered = item["selected"]
        cost = int(item["fitness"][2])
        pref = round(100 - item["fitness"][0], 1)
        sustainability = round(100 - item["fitness"][1], 1)
        coverage = round(100 - item["fitness"][4], 1)
        distance = round(item["fitness"][3], 1)
        day_plans = [[] for _ in range(trip.days)]
        for pos, attraction in enumerate(ordered):
            day_plans[pos % trip.days].append({
                "attraction": attraction,
                "reason": explain(attraction, trip, scores[attraction.id], feedback_ids),
                "score": scores[attraction.id],
            })
        result.append({
            "number": index,
            "attractions": ordered,
            "days": day_plans,
            "preference_score": pref,
            "sustainability_score": sustainability,
            "coverage_score": coverage,
            "stop_count": len(ordered),
            "estimated_cost": cost,
            "travel_distance_km": distance,
            "route_distance_complete": item["fitness"][5] == 0,
            "budget_remaining": max(0, budget - cost),
            "reasons": {a.id: explain(a, trip, scores[a.id], feedback_ids) for a in ordered},
            "algorithm": "NSGA-II",
        })
    return result
