# Implementation status and limitations

Status is based on source inspection and tests run in the current development container. External services and the user's local MySQL instance were not available for end-to-end verification.

## Implemented in source

- Django authentication, password login, registration verification, passwordless OTP login, and password-reset OTP flows.
- OTP values are generated with `secrets`, stored as password hashes, expire after five minutes, are single-use, and stop accepting attempts after five failures.
- Registration OTP resend is POST-only and has a 60-second cooldown. OTP issue requests apply a 60-second cooldown per user and purpose.
- SMTP configuration is environment-based. Email send failures are handled by the registration, OTP login, password reset, and registration resend views.
- Destination discovery, attraction details, search/filter UI, destination comparison, reviews and ratings.
- Personalized rule-based recommendation scoring and explainable recommendation text.
- Feedback-driven preference updates. This is incremental rule-based learning, not a trained machine-learning model.
- Baseline itinerary generation, pace caps, category diversification, nearest-neighbour routing and 2-opt local improvement.
- NSGA-II Pareto alternative generation with non-dominated sorting, crowding distance, tournament selection, crossover, mutation, budget repair, and a coverage objective.
- 0/1 Knapsack attraction selection, integrated into Decision Lab with selection/exclusion explanations.
- Dijkstra and A* shortest-path functions over weighted graphs. Decision Lab uses A* on a proximity graph built from attraction coordinates.
- DBSCAN geographic attraction clustering with a category fallback when coordinate coverage is insufficient.
- Budget/feasibility checks, what-if planning, weather-aware alternatives, minimum-disruption replanning, group preference aggregation with a minority-satisfaction term, sustainability scoring, saved trips, budget expenses, PDF export service, and admin analytics.
- Editable five-category budget allocations with exact 100% validation, decimal expense amounts, and largest-remainder rounding for category targets. A migration adds these fields and rotates legacy group invite codes with a 30-day expiry; it has not been applied to the user's local database.
- Group invitation creation and renewal use random codes with expiry; joining, voting and other state changes are POST-only, and group votes are constrained to attractions in the trip destination.
- Itinerary visit slots use attraction durations with a 30-minute planning buffer. The buffer is not a route-time estimate.
- Decision Lab, dedicated travel assistant page, dark mode, responsive templates and Leaflet trip map.

## Requires local setup or external service verification

- Real email delivery requires valid SMTP credentials in `.env`. The credentials are intentionally not included. SMTP delivery to the user's inbox has not been verified here.
- MySQL integration must be verified against the user's own `smarttrip` database after a backup and migration-history check. Tests in this environment used a temporary SQLite test database.
- Live weather, road routing and external map tiles require internet access. Fallback results are estimates and are labeled accordingly.
- Ollama/OpenAI assistant responses require the corresponding local service or API key. The local deterministic fallback works without an LLM.
- The current Knapsack budget covers attraction costs multiplied by traveler count. It does not independently allocate accommodation, transportation, meals, taxes or booking prices.
- Graph shortest-path edges use straight-line geographic distance unless a real road graph is supplied. The A* route shown in Decision Lab is an estimated POI graph route, not road navigation.
- The public OSRM demo endpoint is suitable for demonstration, not high-volume production traffic.
- The migration `0003_budget_allocations_invite_expiry_decimal_expenses` must be reviewed and backed up before applying to an existing MySQL database. Its data migration rotates active group invite links, so previously shared invite codes will stop working.

## Not claimed

- No trained ML model is included or claimed.
- No live hotel, flight, ticket or transport booking is performed.
- No real-time visitor counts or verified carbon-emissions data are inferred from missing fields.
- No algorithmic improvement claim should be made until baseline and NSGA-II results are compared on repeatable scenarios.
