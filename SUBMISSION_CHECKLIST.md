# SmartTrip AI Submission Checklist

## Included in this package

- Django full-stack application with MySQL as the primary database, targeting `smarttrip` by default.
- Existing destination discovery, ratings/reviews, profiles, saved trips, budgeting, group planning, what-if planning, PDF export and admin analytics.
- Rule-based recommendations, feedback-based preference updates, explainable scoring, feasibility checks and sustainability scoring.
- Baseline itinerary generation using nearest-neighbour route ordering and 2-opt local improvement.
- NSGA-II multi-objective itinerary alternatives in Decision Lab, with a preference, sustainability, cost, distance and itinerary-coverage objective.
- 0/1 Knapsack attraction selection with explanations for selected and excluded attractions.
- Dijkstra and A* graph path functions, with A* proximity-graph analysis displayed in Decision Lab.
- Geographic DBSCAN attraction clustering and category fallback when coordinates are missing.
- Group preference aggregation that combines mean satisfaction with a minority-satisfaction component.
- Configurable email OTP flows, with hashed, expiring, single-use codes, attempt limits, and resend cooldowns.
- Interactive Leaflet itinerary map, OSRM road-route integration with a labeled straight-line fallback, and Open-Meteo weather integration with a labeled fallback.
- Dedicated SmartTrip AI assistant page and optional Ollama/OpenAI integration with local fallback.
- Responsive UI, dark mode, migrations, seeded demo data, algorithm documentation and test results.

## Validation performed during this upgrade

- 30 October 2026: Django system check passed; `makemigrations --check --dry-run` found no missing migrations.
- 30 October 2026: Full `travel` suite passed, 161 tests in 521.368 seconds, using a temporary in-memory SQLite test database. Focused assistant and Copilot tests passed, 35 tests in 104.813 seconds.
- JavaScript syntax check passed for `travel/static/travel/js/app.js`.
- PDF generation/content tests passed as part of the Django suite. A visual PDF rendering inspection was not performed.
- Real SMTP delivery and MySQL connectivity were not re-tested during this isolated test run. Earlier user-reported read-only checks are separate from these results.
- Live weather, routing, external map tiles, configured Ollama/OpenAI services, and a browser-based walkthrough were not verified in this run.

See `docs/TEST_RESULTS.md` and `docs/IMPLEMENTATION_STATUS.md` for the complete limitations.

## Before the college demonstration

1. Extract the ZIP and open the project folder in VS Code.
2. Copy `.env.example` to `.env`. Generate a new Django `SECRET_KEY`, enter MySQL credentials, and keep `DB_NAME=smarttrip` after verifying the existing schema and migration history.
3. Configure valid SMTP credentials. For Gmail, use an app password. Do not share `.env`.
4. Back up your MySQL database before running `python manage.py migrate`.
5. Run `START_HERE.bat`, then test registration and confirm the OTP arrives in your real inbox.
6. Test destination discovery, trip creation, Decision Lab, Knapsack budget selection, route maps, dynamic replanning, what-if planning, group planning and PDF export.
7. Run `python manage.py test` after installing the dependencies on your Windows machine.
8. Compare the baseline itinerary and NSGA-II across repeatable scenarios before claiming one algorithm performs better. Record the measured budget, preference, sustainability, route-distance and runtime results.

## Important limitations to explain accurately

- The preference system uses rule-based scoring and feedback updates. No trained ML model is included.
- The Knapsack module optimizes attraction costs only. It does not independently optimize accommodation, meals or transport.
- A* in Decision Lab uses straight-line distances between POI graph nodes, not road distances or traffic-aware travel times.
- Weather, map tiles, OSRM routing and any external AI provider depend on their service availability and configuration.
- Email OTP requires valid SMTP credentials. Do not claim real delivery until the inbox test succeeds.
