# SmartTrip AI

A Django web application for discovering destinations and building personalized, budget-aware travel itineraries. SmartTrip AI combines explainable recommendation scoring, route and itinerary algorithms, trip budgeting, group planning, and optional AI assistance in one locally runnable project.

## Project overview

Users can explore destinations and attractions, set trip dates and preferences, generate a multi-day itinerary, and manage the resulting plan. Recommendations use profile interests, trip preferences, prior feedback, sustainability priorities, hidden-gem scores, and crowd information where those fields are available.

The project is built as a Django application with server-rendered templates and a service layer for recommendation, itinerary, routing, feasibility, weather fallback, and AI-provider behavior.

## Features

- Account registration with email OTP verification, password login, passwordless OTP login, and OTP password reset
- Destination search and filters, attraction details, destination comparisons, reviews, ratings, and helpful-review feedback
- Personalized, explainable destination and attraction recommendations with incremental preference updates from likes, saves, and dislikes
- Multi-day itinerary generation with pace limits, category diversity, nearest-neighbour ordering, and 2-opt route improvement
- Decision Lab alternatives using NSGA-II multi-objective optimization, 0/1 Knapsack attraction selection, and graph shortest-path utilities (Dijkstra and A*)
- Budget and expense tracking, feasibility checks, saved trips, what-if scenarios, and minimum-disruption replanning
- Group trips with preference aggregation that considers both average and minimum member preference
- Interactive Leaflet itinerary map; OSRM road-route estimates when available, with a labeled straight-line fallback
- Open-Meteo weather lookups when coordinates and forecast dates are available, with clearly labeled offline fallback behavior
- Optional natural-language trip brief parsing and travel assistant using local Ollama or a configured OpenAI-compatible API; deterministic local behavior remains available without an LLM
- Sustainability scoring, hidden-gem signals, PDF itinerary export, and an admin analytics dashboard
- Responsive templates, dark mode, and Django admin

Feature behavior depends on available project data and optional external services. SmartTrip AI does not book flights, hotels, tickets, or transportation. Recommendation feedback updates rule-based preferences; the project does not include a trained machine-learning model.

## Technology

- **Backend:** Python, Django 5.2
- **Database:** MySQL by default; SQLite is available for local development
- **Frontend:** Django templates, HTML, CSS, JavaScript, Leaflet
- **Algorithms:** rule-based ranking, nearest neighbour, 2-opt, NSGA-II, 0/1 Knapsack, DBSCAN, Dijkstra, and A*
- **Optional integrations:** SMTP email, Ollama, OpenAI-compatible chat completions, Open-Meteo weather, and OSRM route estimates
- **PDF export:** ReportLab and Pillow

## Architecture and workflow

The project is organized around the Django application and its travel domain:

```text
smarttrip/                 Django settings and URL configuration
travel/
  models.py                Users' profiles, destinations, trips, and related data
  views.py                 Request handling and page workflows
  services/                Recommendations, itinerary optimization, AI, maps, weather, PDF, and more
  templates/travel/        Application pages
  static/travel/           CSS, JavaScript, and images
  migrations/              Database schema history
docs/                      Algorithm, implementation, and test notes
database/                  Database setup SQL and documentation
```

At a high level, a user selects a destination, dates, budget, pace, and interests. The application combines those constraints with destination and attraction records, scores candidate attractions, and generates an itinerary. Users can review alternatives, save or adjust trips, record expenses, and provide feedback. Feedback updates preference values using fixed rule-based increments.

External integrations are optional and have fallbacks where implemented. Map tiles, OSRM, Open-Meteo, SMTP, and AI providers require their respective configuration or network access. Algorithm details and limitations are documented in [docs/ALGORITHMS.md](docs/ALGORITHMS.md).

## Requirements

- Python 3.10 or newer
- MySQL Server for the default configuration, or SQLite for local development
- Internet access when installing packages or using external map, weather, email, or AI services

## Setup

### Windows quick start (MySQL)

1. Install Python and MySQL Server, then start MySQL.
2. Back up any existing `smarttrip` database and review its migration history before applying migrations.
3. Create the database using MySQL Workbench or the MySQL client:

   ```powershell
   mysql -u root -p < database\create_mysql_database.sql
   ```

   The SQL creates the database if it does not exist; it does not drop tables.
4. Copy the example configuration and edit the local values:

   ```powershell
   Copy-Item .env.example .env
   ```

   Set the MySQL credentials and SMTP settings as needed. Keep `.env` private.
5. Run `START_HERE.bat`. It creates a virtual environment, installs requirements, runs migrations, loads seed data, checks Django, and starts the development server.

### Manual setup

From the repository directory:

```powershell
python -m venv venv
venv\Scripts\Activate.ps1
Copy-Item .env.example .env
python -m pip install -r requirements.txt
python manage.py migrate
python manage.py seed_data
python manage.py check
python manage.py runserver
```

Open [http://127.0.0.1:8000/](http://127.0.0.1:8000/).

For SQLite development, set `DB_ENGINE=sqlite` in `.env`. The SQLite database file is created locally by Django. MySQL remains the default.

## Environment configuration

The application reads key-value settings from `.env` (or the process environment). Start from [.env.example](.env.example).

| Setting | Purpose |
| --- | --- |
| `SECRET_KEY` | Django secret; replace the example value before use beyond local development |
| `DEBUG` | Debug mode; enabled in the example for local development |
| `ALLOWED_HOSTS` | Comma-separated host names |
| `DB_ENGINE` | `mysql` (default) or `sqlite` |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | MySQL connection settings |
| `EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS`, `DEFAULT_FROM_EMAIL` | SMTP configuration for OTP and account email |
| `AI_PROVIDER` | AI selection mode; supports local fallback and optional Ollama/OpenAI configuration |
| `AI_ALLOW_PAID_FALLBACK` | Whether automatic provider selection may fall back to a hosted API |
| `OLLAMA_BASE_URL`, `OLLAMA_MODEL` | Local Ollama endpoint and model |
| `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_BASE_URL` | Optional OpenAI-compatible API configuration |
| `SMARTTRIP_OSRM_ROUTING_URL` | Optional OSRM routing endpoint; the public demo endpoint is the default |
| `SMARTTRIP_MAP_TILE_URL`, `SMARTTRIP_MAP_TILE_ATTRIBUTION` | Optional map tile provider settings |

For local generative assistance with Ollama, install and start Ollama, then configure `AI_PROVIDER=ollama`, `OLLAMA_BASE_URL`, and `OLLAMA_MODEL`. For hosted AI, configure the API key and provider settings; hosted API usage may incur charges. Without an available provider, the local deterministic assistant and trip-brief behavior remain available.

OTP email delivery requires valid SMTP credentials. For offline development, Django's console email backend can be selected in `.env`; this prints messages locally and does not deliver email.

Never commit `.env`, API keys, email credentials, or production secrets.

## Testing and verification

The repository's recorded verification is in [docs/TEST_RESULTS.md](docs/TEST_RESULTS.md). It reports:

- Django system check and migration consistency check passed with SQLite
- 29 Django tests passed, excluding the PDF rendering test
- Direct algorithm assertions for Dijkstra, A*, nearest-neighbour/2-opt, and Knapsack passed
- Python compilation checks passed

The PDF rendering test could not be validated in the recorded environment because its bundled Windows Pillow/ReportLab extensions could not load in Linux. SMTP delivery to a real mailbox and connection to the project's MySQL database were also not verified. See [docs/IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md) for external-service requirements, data limitations, and unsupported claims. Treat these as the documented results, not a guarantee for every machine or configuration.

## Screenshots and demo

No verified screenshots, demo recording, or deployed application URL are included in this repository. Add current screenshots or a demo link here when they are available and checked into the project.

## Future enhancements

Ideas consistent with the current project include:

- Add repeatable benchmark scenarios comparing baseline itineraries and NSGA-II alternatives
- Expand budget modeling to cover accommodation, transportation, meals, taxes, and price changes
- Verify and document the PDF export, MySQL setup, and SMTP flow in a clean supported environment
- Add curated, regularly maintained destination and attraction data with clear provenance
- Improve provider configuration and operational guidance before any production deployment

These are potential next steps, not current capabilities.

## Contributing

Contributions are welcome. Open an issue to discuss a bug or proposed change, then submit a focused pull request with a clear summary and verification steps. For algorithm changes, include reproducible scenarios and describe relevant data assumptions. Avoid committing secrets, local databases, virtual environments, or generated user data.

## Contact

Created by [@shreyaskumbar-18](https://github.com/shreyaskumbar-18). For questions or project feedback, use the repository's GitHub issues.

## Project notes

- See [docs/ALGORITHMS.md](docs/ALGORITHMS.md) for algorithm descriptions and complexity notes.
- See [docs/IMPLEMENTATION_STATUS.md](docs/IMPLEMENTATION_STATUS.md) for implemented behavior and limitations.
- See [docs/TEST_RESULTS.md](docs/TEST_RESULTS.md) for the recorded checks and test outcomes.
- See [database/README.md](database/README.md) and [MYSQL_SETUP.txt](MYSQL_SETUP.txt) for database setup details.
