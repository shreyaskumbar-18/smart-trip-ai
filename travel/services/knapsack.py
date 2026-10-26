"""Budget-aware 0/1 knapsack selection for attraction recommendations."""
from __future__ import annotations


def select_attractions_knapsack(attractions, budget, travelers=1, scores=None, max_items=None):
    """Select a value-maximizing set of attractions under a total cost budget.

    Attraction costs are multiplied by traveler count. This is an attraction-only
    budget model; accommodation, transport and meals must be budgeted separately.
    Returns selected items, total cost/value, and per-item selection explanations.
    """
    attractions = list(attractions)
    budget = max(0, int(budget or 0))
    travelers = max(1, int(travelers or 1))
    scores = scores or {}
    if not attractions or budget <= 0:
        return {"selected": [], "total_cost": 0, "total_value": 0.0, "budget": budget, "explanations": []}

    # Sparse DP states are keyed by (cost, selected_count). Keeping count in the
    # state is necessary when max_items is active, because a cheap state with
    # many items does not always dominate a state with fewer items.
    states = {(0, 0): (0.0, ())}
    for index, attraction in enumerate(attractions):
        unit_cost = max(0, int(getattr(attraction, "estimated_cost", 0) or 0)) * travelers
        value = float(scores.get(getattr(attraction, "id", index), 0.0))
        if value <= 0:
            value = 1.0
        updates = dict(states)
        for (cost, count), (total_value, picked) in states.items():
            if max_items is not None and count >= max_items:
                continue
            new_cost = cost + unit_cost
            new_count = count + 1
            if new_cost > budget:
                continue
            candidate = (total_value + value, picked + (index,))
            key = (new_cost, new_count)
            existing = updates.get(key)
            if existing is None or candidate[0] > existing[0]:
                updates[key] = candidate

        # Within the same selected-count layer, cheaper states with at least as
        # much value dominate more expensive states. Keep different counts.
        pruned = {}
        max_value_by_count = {}
        for (cost, count), state in sorted(updates.items(), key=lambda pair: (pair[0][1], pair[0][0])):
            value_at_state, picked = state
            if value_at_state > max_value_by_count.get(count, -1.0):
                pruned[(cost, count)] = state
                max_value_by_count[count] = value_at_state
        states = pruned

    (total_cost, _), (total_value, picked_indices) = max(
        states.items(), key=lambda pair: (pair[1][0], -pair[0][0], -pair[0][1])
    )
    picked_set = set(picked_indices)
    selected = [attractions[i] for i in picked_indices]
    explanations = []
    for index, attraction in enumerate(attractions):
        cost = max(0, int(getattr(attraction, "estimated_cost", 0) or 0)) * travelers
        if index in picked_set:
            reason = "Selected because its score fits the remaining attraction budget."
        elif cost > budget:
            reason = "Excluded because its estimated cost exceeds the full attraction budget."
        else:
            reason = "Excluded because other available attractions provide a higher total score within the budget."
        explanations.append({"attraction": attraction, "cost": cost, "selected": index in picked_set, "reason": reason})
    return {"selected": selected, "total_cost": total_cost, "total_value": round(total_value, 2), "budget": budget, "explanations": explanations}
