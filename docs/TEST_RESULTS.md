# Test results

Test date: 30 October 2026.

## Checks run

- Django system check with the database overridden to in-memory SQLite before setup: passed with no issues.
- `makemigrations --check --dry-run` with the same process-scoped in-memory SQLite override: passed; no model changes were missing from migrations.
- Focused assistant and Copilot tests: 35 passed in 104.813 seconds.
- Full `manage.py test travel`: 161 tests passed in 521.368 seconds.
- `node --check travel/static/travel/js/app.js`: passed.

The tests used Django's temporary in-memory SQLite test database. The test runner created and destroyed that database. They cover authentication and OTP handling, trip and itinerary behavior, recommendation and optimization services, budget allocations and expenses, group invitations and voting, weather/replanning behavior, PDF export, assistant and Copilot workflows, and page rendering. MySQL was not contacted; the local `db.sqlite3` and MySQL data were not changed.

## Runtime details and limits

The checks and tests were run with Python 3.13.1 and the project's installed packages. Pillow and ReportLab loaded successfully during the passing PDF tests.

This run does not verify the user's MySQL connection or schema, real SMTP delivery, live Open-Meteo responses, public OSRM routes, external map tiles, or a locally configured Ollama/OpenAI provider. Those need environment-specific verification. No browser-based manual walkthrough was performed during this run.
