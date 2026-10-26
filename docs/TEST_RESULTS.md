# Test results

Test date: 18 October 2026.

## Checks run

- `python manage.py check` with `DB_ENGINE=sqlite`: passed, no issues reported.
- `python manage.py makemigrations --check --dry-run` with `DB_ENGINE=sqlite`: passed, no model changes detected.
- 29 Django tests excluding the PDF rendering test: passed.
- Additional direct algorithm assertions for Dijkstra, A*, nearest-neighbour/2-opt and Knapsack: passed.
- Python `compileall` over the Django project: passed.

The 29 passing Django tests cover service behavior, preference updates, weather fallback, itinerary repair, trip planner and detail rendering, Decision Lab rendering, OTP hashing/email/single-use behavior, geographic DBSCAN, graph paths, and Knapsack budget limits.

## Environment limitation

The uploaded ZIP contained a Windows virtual environment. Its compiled Pillow/ReportLab extensions cannot load in the Linux inspection container. The PDF rendering test therefore could not be validated in this environment. `reportlab` and `Pillow` remain declared in `requirements.txt`, so reinstalling requirements in a native Windows virtual environment is required before testing PDF export there.

SMTP delivery to a real mailbox and connection to the user's MySQL server were not tested because private credentials and the local database service were not available. Do not describe either as verified until tested on the user's laptop.
