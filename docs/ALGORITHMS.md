# SmartTrip AI algorithm reference

This document describes implemented algorithmic services in this project. Metrics are only as reliable as the data supplied by the destination and attraction records.

## 1. Personalized attraction scoring

`travel/services/recommendation.py` calculates a bounded score from the selected trip interest, learned category preferences, matching preference terms, sustainability priority, hidden-gem preference, crowd score, positive feedback and negative feedback. The final score is clamped to 0..100. This is explainable rule-based scoring, not a trained machine-learning model.

## 2. Baseline itinerary generation

`travel/services/optimizer.py` ranks attractions, limits the number of stops by pace, diversifies categories, distributes attractions over days, and orders each day using nearest-neighbour routing followed by a bounded 2-opt local search. Suggested visit slots use each attraction's `duration_hours`, start at 09:00, include a 30-minute planning buffer between stops, and keep each day within a 10-hour planning window. The buffer is not a travel-time estimate. The 2-opt step reverses route segments when doing so reduces the sum of pairwise Haversine distances.

Nearest-neighbour construction is O(n^2). A full 2-opt pass is O(n^2), and this implementation bounds the number of passes to 25. Haversine distances are straight-line estimates, not road distances or travel-time predictions.

## 3. NSGA-II multi-objective itinerary alternatives

`travel/services/nsga2.py` uses binary attraction-selection chromosomes, non-dominated sorting, crowding distance, tournament selection, uniform crossover, bit-flip mutation and constraint repair. The objective vector is minimized: (100 - average preference score, 100 - average sustainability score, estimated attraction cost, estimated inter-attraction distance, 100 - itinerary coverage, and a penalty for missing coordinates). The coverage objective reduces the tendency to favor one-stop plans solely because they have low cost and zero route distance. Missing coordinates are not treated as zero distance. The service returns non-dominated alternatives, rather than claiming a single plan is best for every traveler.

With population size N, generation count G, and M objectives, non-dominated sorting dominates runtime at approximately O(G*M*N^2), with additional work for chromosome evaluation and route calculations. The implementation limits the candidate pool to 36 attractions.

The hard cost constraint currently covers attraction cost multiplied by traveler count. It does not itself model accommodation, transport, meals, taxes, or real-time prices. Those belong in the broader trip budget/feasibility calculation.

## 4. 0/1 Knapsack attraction selection

`travel/services/knapsack.py` selects each attraction zero or one time, maximizing the sum of recommendation values without exceeding the attraction-only budget. Each attraction's estimated cost is multiplied by traveler count. The sparse dynamic-programming state tracks reachable costs and best values, then prunes dominated states. The worst-case number of sparse states can grow substantially with input size, so keep candidate pools bounded for large budgets.

This is shown in Decision Lab as a separate budget-focused comparison, with a per-attraction explanation. It does not replace the full trip budget calculation.

## 5. Graph shortest paths

`travel/services/route_algorithms.py` provides Dijkstra's algorithm and A* over a caller-supplied weighted adjacency graph. Dijkstra requires non-negative weights and has O((V+E) log V) complexity with a binary heap. A* has the same worst-case order, depending on heuristic quality. When edge weights are road distances, the Haversine heuristic is suitable only when it is a lower bound on those weights.

`build_geographic_graph` builds a proximity graph from attraction coordinates, and `plan_geographic_path` integrates A* into Decision Lab between the first and last stop of the leading Pareto alternative. These are estimated straight-line graph paths, not a road graph. The map's OSRM integration should be used for road-route display when the external routing service responds. The fallback must be labeled as an estimate.

## 6. Feedback-based preference updates

`travel/services/learning.py` adjusts category preference values by a fixed increment for likes/saves and decrement for dislikes, clamped to [0,1]. It is incremental rule-based preference learning, not a fitted predictive model.

## 7. Feasibility and repair

`travel/services/feasibility.py` checks hard schedule/data issues and reports advisory recommendations separately, including budget, pace, duration and straight-line distance limitations where detectable. `travel/services/repair.py` attempts minimum-disruption changes and records reasons. Weather behavior depends on live weather availability; fallback conditions are labeled as demo/offline data and do not trigger a weather-based replan.

## 8. Geographic clustering

`travel/services/poi.py` uses dependency-free DBSCAN over Haversine distance when enough attractions have coordinates. The default neighborhood radius is 5 km and `min_samples` is 2. Coordinate-missing attractions are grouped by category, and geographic outliers are labeled rather than silently discarded. If too few attractions have coordinates, the service explicitly falls back to category grouping. DBSCAN can form clusters of arbitrary shape, but results depend on the radius and data quality.

## 9. Group preference aggregation

`aggregate_group_preferences` computes each category's score as 70% mean member preference plus 30% minimum member preference. This transparent heuristic gives some weight to the least-satisfied member instead of selecting only the strongest average. It is a compromise score, not a guarantee of equal satisfaction.

## Evaluation recommendations

Compare the baseline optimizer and NSGA-II with identical destination data and constraints. Record feasibility rate, attraction cost, preference score, sustainability score, estimated straight-line distance, and runtime over multiple fixed seeds. Do not claim the optimizer improves results until those measurements support the claim.
