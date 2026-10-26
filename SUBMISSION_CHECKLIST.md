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

- Django system check: passed with SQLite test configuration.
- Migration consistency check: passed, no model changes detected.
- 27 Django tests: passed. These cover algorithms, route paths, geographic clustering, group preference aggregation, OTP hash/email/single-use behavior, key page rendering, trip creation, itinerary repair and weather fallback.
- Python source compilation: passed.
- PDF rendering test: not verified in the inspection container because the uploaded Windows virtual environment contains compiled Pillow/ReportLab extensions that cannot load on Linux. Reinstall dependencies in a native Windows virtual environment and run the full suite.
- Real SMTP delivery and connection to the user's MySQL database: not verified because private credentials and the user's local MySQL service were not available.

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
