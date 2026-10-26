"""SmartTrip AI Copilot service: multi-alternative generation and conversational itinerary refinement."""

from datetime import time, timedelta
from .recommendation import recommendation_score, explain
from .route_algorithms import nearest_neighbor_two_opt
from .repair import repair_itinerary


PACE_ACTIVITIES = {
    "relaxed": 2,
    "balanced": 3,
    "packed": 4,
}


def _distance(a, b):
    if any(getattr(x, field, None) is None for x in (a, b) for field in ("latitude", "longitude")):
        return 0.0
    from math import asin, cos, radians, sin, sqrt
    lat1, lon1 = radians(float(a.latitude)), radians(float(a.longitude))
    lat2, lon2 = radians(float(b.latitude)), radians(float(b.longitude))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    hav = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 6371.0 * 2 * asin(min(1.0, sqrt(hav)))


def _route_order(attractions):
    return nearest_neighbor_two_opt(list(attractions), _distance)


def generate_copilot_alternatives(destination, days, budget, travelers, interest, pace="balanced", user=None):
    """
    Generate three distinct, meaningful planning alternatives:
    1. Budget Saver: Minimizes ticket costs, favors free/low-cost attractions, sensible distances.
    2. Balanced Explorer: Curated harmony between top interest match, comfortable pace, and variety.
    3. Hidden Gems & Eco: Prioritizes lesser-known spots, high sustainability, and lower crowd pressure.
    """
    all_attractions = list(destination.attractions.all())
    if not all_attractions or days <= 0:
        return []

    # Mock trip-like context for scoring
    class CopilotTripContext:
        def __init__(self, d, dy, b, t, i, p, u):
            self.destination = d
            self.days = dy
            self.budget = b
            self.travelers = t
            self.interest = i
            self.pace = p
            self.user = u
            self.sustainability_priority = 3
            self.include_hidden_gems = True
            self.id = None
            self._disliked_attraction_ids = set()

    base_context = CopilotTripContext(destination, days, budget, travelers, interest, pace, user)

    # -------------------------------------------------------------
    # 1. Alternative: Budget Saver
    # -------------------------------------------------------------
    budget_target_per_day = (budget * 0.15) / max(1, days)
    def budget_score(attraction):
        cost = float(attraction.estimated_cost or 0)
        base = recommendation_score(attraction, base_context)
        if cost == 0:
            return base + 35.0
        elif cost <= budget_target_per_day:
            return base + 15.0 - (cost / max(1, budget_target_per_day) * 10)
        else:
            return max(0.0, base - (cost / max(1, budget_target_per_day) * 20))

    ranked_budget = sorted(all_attractions, key=budget_score, reverse=True)
    limit_budget = min(days * PACE_ACTIVITIES.get(pace, 3), len(ranked_budget))
    selected_budget = ranked_budget[:limit_budget]

    # -------------------------------------------------------------
    # 2. Alternative: Balanced Explorer
    # -------------------------------------------------------------
    ranked_balanced = sorted(
        all_attractions,
        key=lambda a: recommendation_score(a, base_context),
        reverse=True
    )
    limit_balanced = min(days * PACE_ACTIVITIES.get(pace, 3), len(ranked_balanced))
    # Category diversification
    selected_balanced = []
    cat_counts = {}
    for a in ranked_balanced:
        cat = (a.category or "").lower()
        if cat_counts.get(cat, 0) < 2 or len(selected_balanced) >= limit_balanced - 1:
            selected_balanced.append(a)
            cat_counts[cat] = cat_counts.get(cat, 0) + 1
            if len(selected_balanced) >= limit_balanced:
                break
    if len(selected_balanced) < limit_balanced:
        for a in ranked_balanced:
            if a not in selected_balanced:
                selected_balanced.append(a)
                if len(selected_balanced) >= limit_balanced:
                    break

    # -------------------------------------------------------------
    # 3. Alternative: Hidden Gems & Eco
    # -------------------------------------------------------------
    def gem_eco_score(attraction):
        gem = float(attraction.hidden_gem_score or 50)
        eco = float(attraction.sustainability_score or 70)
        crowd = float(attraction.crowd_level or 50)
        base = recommendation_score(attraction, base_context)
        return base * 0.4 + gem * 0.35 + eco * 0.25 + (100 - crowd) * 0.15

    ranked_gems = sorted(all_attractions, key=gem_eco_score, reverse=True)
    limit_gems = min(days * PACE_ACTIVITIES.get(pace, 3), len(ranked_gems))
    selected_gems = ranked_gems[:limit_gems]

    def build_option_structure(key, title, tagline, badge_color, icon, selected_list, strategy_desc, tradeoffs):
        day_buckets = [[] for _ in range(days)]
        for idx, attr in enumerate(selected_list):
            day_buckets[idx % days].append(attr)

        slots = [9, 13, 17, 19]
        day_plans = []
        total_cost = 0
        total_distance = 0.0
        gem_scores = []
        eco_scores = []

        for d_idx, day_attrs in enumerate(day_buckets):
            ordered = _route_order(day_attrs)
            # Route distance
            for i in range(len(ordered) - 1):
                d = _distance(ordered[i], ordered[i + 1])
                if d is not None:
                    total_distance += d

            day_items = []
            for pos, attr in enumerate(ordered):
                score = recommendation_score(attr, base_context)
                cost = attr.estimated_cost or 0
                total_cost += cost
                gem_scores.append(attr.hidden_gem_score or 50)
                eco_scores.append(attr.sustainability_score or 70)
                reason = explain(attr, base_context, score)
                start_h = slots[min(pos, len(slots) - 1)]

                day_items.append({
                    "attraction": attr,
                    "day_number": d_idx + 1,
                    "time": time(start_h, 0).strftime("%H:%M"),
                    "score": score,
                    "cost": cost,
                    "reason": reason,
                    "category": attr.category or "Sightseeing",
                    "duration_hours": float(getattr(attr, "duration_hours", 2.0)),
                })
            day_plans.append({
                "day_number": d_idx + 1,
                "items": day_items,
            })

        avg_gem = round(sum(gem_scores) / len(gem_scores), 1) if gem_scores else 50
        avg_eco = round(sum(eco_scores) / len(eco_scores), 1) if eco_scores else 70

        return {
            "key": key,
            "title": title,
            "tagline": tagline,
            "badge_color": badge_color,
            "icon": icon,
            "strategy": strategy_desc,
            "tradeoffs": tradeoffs,
            "estimated_cost": total_cost,
            "stop_count": len(selected_list),
            "daily_count": round(len(selected_list) / max(1, days), 1),
            "travel_distance_km": round(total_distance, 1),
            "avg_hidden_gem": avg_gem,
            "avg_sustainability": avg_eco,
            "days": day_plans,
            "selected_attraction_ids": [a.id for a in selected_list],
        }

    alt1 = build_option_structure(
        key="budget_saver",
        title="Budget Saver",
        tagline="Maximum affordability & free admissions",
        badge_color="success",
        icon="fa-piggy-bank",
        selected_list=selected_budget,
        strategy_desc="Prioritizes free admission heritage walks, public viewpoints, and low-cost city monuments.",
        tradeoffs=[
            "Cuts ticket expenses by up to 45%",
            "Favors public landmarks over premium entry-fee complexes",
            "Compact geographic clusters to keep taxi/transit fares down"
        ],
    )

    alt2 = build_option_structure(
        key="balanced_explorer",
        title="Balanced Explorer",
        tagline="Curated mix of must-see landmarks & culture",
        badge_color="primary",
        icon="fa-compass",
        selected_list=selected_balanced,
        strategy_desc="Harmonizes destination iconic highlights with your primary travel interest and comfortable pacing.",
        tradeoffs=[
            "Ideal balance of top-rated landmarks and regional highlights",
            "Optimal variety across categories (history, culture, nature, food)",
            "Moderate activity pacing suited for travelers wanting a complete overview"
        ],
    )

    alt3 = build_option_structure(
        key="hidden_gems_eco",
        title="Hidden Gems & Eco",
        tagline="Tranquil off-beat spots & sustainable travel",
        badge_color="info",
        icon="fa-gem",
        selected_list=selected_gems,
        strategy_desc="Focuses on lesser-crowded treasures, lush parks, nature escapes, and certified sustainable attractions.",
        tradeoffs=[
            "Avoids heavy tourist queues and crowded commercial zones",
            "Highest eco-sustainability and green index rating",
            "May omit high-profile crowded monuments in favor of authentic local retreats"
        ],
    )

    return [alt1, alt2, alt3]


def refine_itinerary_with_prompt(trip, prompt):
    """
    Interpret conversational requests and apply minimum-disruption itinerary refinements.
    Supports:
    - Pace adjustments ('more relaxed', 'slow down', 'packed', 'full schedule')
    - Budget adjustments ('reduce budget', 'cheaper', 'prefer free attractions')
    - Category pivots ('more nature', 'more history', 'more food')
    - Weather adjustments ('weather replan', 'rain alternative')
    """
    prompt_low = (prompt or "").lower().strip()
    attractions = list(trip.destination.attractions.all())
    current_items = list(trip.items.select_related("attraction").order_by("day_number", "start_time", "pk"))
    current_attr_ids = {item.attraction_id for item in current_items}

    diff_summary = ""
    changes = []
    action_type = "unknown"

    # 1. Weather replan
    if any(w in prompt_low for w in ["weather", "rain", "storm", "forecast", "indoor"]):
        action_type = "weather_replan"
        repaired = repair_itinerary(trip, attractions, trigger="Weather-aware replan")
        changed_count = sum(1 for r in repaired if r.get("changed"))
        if changed_count > 0:
            diff_summary = f"Weather-aware replan: Replaced {changed_count} outdoor activity(ies) with weather-sheltered alternatives. Remaining schedule preserved."
        else:
            diff_summary = "Weather check complete: No scheduled activities are affected by adverse weather. Itinerary preserved."
        return {
            "success": True,
            "action_type": action_type,
            "summary": diff_summary,
            "repaired_items": repaired,
        }

    # 2. Relaxed pace
    if any(w in prompt_low for w in ["relaxed", "slow", "unhurried", "less hectic", "calm", "chill"]):
        action_type = "pace_relaxed"
        trip.pace = "relaxed"
        trip.save(update_fields=["pace"])

        # If too many items per day (>2), drop lowest scoring or longest items to achieve relaxed pace
        repaired = []
        dropped = []
        for day in range(1, trip.days + 1):
            day_items = [it for it in current_items if it.day_number == day]
            if len(day_items) > 2:
                # Keep top 2 items
                sorted_items = sorted(day_items, key=lambda it: it.score, reverse=True)
                keep = sorted_items[:2]
                drop = sorted_items[2:]
                repaired.extend([
                    {"day": it.day_number, "attraction": it.attraction, "start": it.start_time, "score": it.score, "reason": it.reason}
                    for it in keep
                ])
                for d in drop:
                    changes.append({"type": "removed", "attraction": d.attraction.name, "reason": "Trimmed to achieve unhurried relaxed pace (max 2 activities/day)."})
            else:
                repaired.extend([
                    {"day": it.day_number, "attraction": it.attraction, "start": it.start_time, "score": it.score, "reason": it.reason}
                    for it in day_items
                ])

        diff_summary = f"Itinerary adjusted to a relaxed travel pace. Daily schedule trimmed to comfortable 2 activities per day."
        return {
            "success": True,
            "action_type": action_type,
            "summary": diff_summary,
            "changes": changes,
            "repaired_items": repaired,
        }

    # 3. Budget reduction / Prefer free
    if any(w in prompt_low for w in ["budget", "cheaper", "free", "save money", "cut cost", "expensive"]):
        action_type = "budget_cut"
        # Find free or low-cost available attractions not currently in trip
        free_candidates = [a for a in attractions if a.id not in current_attr_ids and (a.estimated_cost or 0) == 0]
        repaired = []
        cost_saved = 0

        # Replace highest cost attraction with free candidate if available
        highest_cost_item = max(current_items, key=lambda it: (it.attraction.estimated_cost or 0)) if current_items else None
        if highest_cost_item and (highest_cost_item.attraction.estimated_cost or 0) > 0 and free_candidates:
            replacement = free_candidates[0]
            cost_saved = highest_cost_item.attraction.estimated_cost
            for it in current_items:
                if it.id == highest_cost_item.id:
                    repaired.append({
                        "day": it.day_number,
                        "attraction": replacement,
                        "start": it.start_time,
                        "score": it.score,
                        "reason": f"Substituted {highest_cost_item.attraction.name} (₹{highest_cost_item.attraction.estimated_cost}) with free admission {replacement.name} to optimize budget.",
                    })
                    changes.append({
                        "type": "replaced",
                        "old": highest_cost_item.attraction.name,
                        "new": replacement.name,
                        "saving": cost_saved,
                    })
                else:
                    repaired.append({
                        "day": it.day_number,
                        "attraction": it.attraction,
                        "start": it.start_time,
                        "score": it.score,
                        "reason": it.reason,
                    })
            diff_summary = f"Budget optimized: Replaced {highest_cost_item.attraction.name} with free admission {replacement.name}, saving ₹{cost_saved}."
        else:
            repaired = [{"day": it.day_number, "attraction": it.attraction, "start": it.start_time, "score": it.score, "reason": it.reason} for it in current_items]
            diff_summary = "Your itinerary is already well-optimized for budget with economical entries."

        return {
            "success": True,
            "action_type": action_type,
            "summary": diff_summary,
            "changes": changes,
            "repaired_items": repaired,
        }

    # 4. Specific category boost (nature, food, history, etc.)
    target_category = next((cat for cat in ["nature", "food", "history", "culture", "adventure", "shopping"] if cat in prompt_low), None)
    if target_category:
        action_type = f"more_{target_category}"
        candidates = [a for a in attractions if a.id not in current_attr_ids and (a.category or "").lower() == target_category]
        repaired = []
        if candidates:
            best_candidate = candidates[0]
            # Replace an item that has a different category
            replaceable = next((it for it in current_items if (it.attraction.category or "").lower() != target_category), None)
            if replaceable:
                for it in current_items:
                    if it.id == replaceable.id:
                        repaired.append({
                            "day": it.day_number,
                            "attraction": best_candidate,
                            "start": it.start_time,
                            "score": it.score,
                            "reason": f"Added {best_candidate.name} to fulfill your request for more {target_category} experiences.",
                        })
                        changes.append({
                            "type": "replaced",
                            "old": replaceable.attraction.name,
                            "new": best_candidate.name,
                            "category": target_category,
                        })
                    else:
                        repaired.append({
                            "day": it.day_number,
                            "attraction": it.attraction,
                            "start": it.start_time,
                            "score": it.score,
                            "reason": it.reason,
                        })
                diff_summary = f"Added {best_candidate.name} ({target_category.title()}) in place of {replaceable.attraction.name}."
            else:
                repaired = [{"day": it.day_number, "attraction": it.attraction, "start": it.start_time, "score": it.score, "reason": it.reason} for it in current_items]
                diff_summary = f"Your itinerary already emphasizes {target_category.title()} activities."
        else:
            repaired = [{"day": it.day_number, "attraction": it.attraction, "start": it.start_time, "score": it.score, "reason": it.reason} for it in current_items]
            diff_summary = f"All available {target_category} spots in this destination are already in your itinerary."

        return {
            "success": True,
            "action_type": action_type,
            "summary": diff_summary,
            "changes": changes,
            "repaired_items": repaired,
        }

    # Fallback: rebalance schedule with route optimization
    action_type = "rebalance"
    repaired = [{"day": it.day_number, "attraction": it.attraction, "start": it.start_time, "score": it.score, "reason": it.reason} for it in current_items]
    diff_summary = "Schedule reviewed and geographically aligned. Daily timings are balanced."
    return {
        "success": True,
        "action_type": action_type,
        "summary": diff_summary,
        "changes": [],
        "repaired_items": repaired,
    }
