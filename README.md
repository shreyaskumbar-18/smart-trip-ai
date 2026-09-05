# SmartTrip AI - An Intelligent Travel Planning and Tourism Management System

**USP: "One Trip. One App."**

SmartTrip AI is a full-stack Django web application that manages the complete travel journey from one centralized trip workspace: AI-assisted planning, personalized itineraries, smart budgeting, route optimization, weather-aware planning, group collaboration, voting, Splitwise-style expense settlement, an interactive map, a trip assistant, checklist, journal and analytics.

---

> Package integrity: this version includes the runtime modules used by `core/views.py`, the app URL configuration, the `seed_data` management command, and the Django templates required by the views.

## 1. Problem Statement

Travelers juggle many disconnected apps for one holiday: a planner, a map, a budget sheet, an expense splitter, a group chat and a weather app. Data never flows between them. SmartTrip AI solves this by making **one trip = one workspace = one app** - every feature is connected to the same Trip object.

## 2. Objectives

- Provide a complete trip workspace covering planning, optimizing, collaborating, spending, adapting, managing and remembering.
- Implement 8 real algorithms that solve genuine travel problems (no fake AI claims).
- Support group travel: shared itinerary, voting, shared expenses and settlement.
- Remain fully functional without any paid/external API keys via built-in fallbacks.

## 3. Features

| Area | Features |
|------|----------|
| Planning | AI itinerary generation, manual itinerary editing, recommendations with explanations, saved trips |
| Optimization | TSP route optimization, Dijkstra shortest path, fractional knapsack activity selection |
| Budget | Style-based allocation, per-person/per-day breakdown, currency snapshot, expense analytics |
| Group | Members and roles, invitations, group voting, shared expenses, minimum-cash-flow settlement |
| Adaptation | 7-day forecast, weather suitability scores, one-click weather-aware replanning |
| Memory | Trip journal (with photos), packing checklist, trip readiness score, analytics dashboard |
| Platform | Authentication, profiles, destination explorer, interactive Leaflet map, Django admin |

## 4. Technology Stack

- **Backend:** Python 3.10+, Django 4.2
- **Frontend:** Django Templates, HTML5, CSS3, JavaScript (ES6), Bootstrap 5, Font Awesome, Leaflet (OpenStreetMap), Chart.js
- **Database:** MySQL 8 (SQLite fallback available for quick demos)
- **APIs:** OpenWeatherMap (optional), open.er-api.com currency rates (optional) - both have offline fallbacks
- **Tools:** Git, GitHub, VS Code, Postman, MySQL Workbench

## 5. Architecture

Classic Django MVT in a single well-organized app:

    Browser (Bootstrap templates + JS)
        -> urls.py -> views.py (authorization, orchestration)
            -> algorithms.py      (TSP, Knapsack, Dijkstra, K-Means, scoring, settlement)
            -> recommendations.py (content-based engine)
            -> services.py        (weather, currency, trip score, assistant)
            -> models.py          (17 models around the central Trip object)
        -> MySQL

## 6. Database Design (main models)

User, UserProfile, Destination, Place, Hotel, Trip, TripMember, ItineraryItem, Expense, ExpenseParticipant, Vote, VoteOption, VoteResponse, Recommendation, SavedTrip, TripJournal, ChecklistItem. All trip features hang off the Trip foreign key; group features join through TripMember.

## 7. Algorithms (all really used)

1. **TSP** (brute force <= 8 points, nearest-neighbour + 2-opt beyond) - orders map routes and each itinerary day. Complexity: O(n!) exact / O(n^2) heuristic per pass.
2. **Fractional Knapsack** - picks best-value activities inside the Activities budget slice. O(n log n).
3. **Dijkstra** - shortest path between two places over a 3-nearest-neighbour graph. O((V+E) log V).
4. **K-Means** - clusters recommended places into geographic day-groups. O(n k i).
5. **Content-Based Recommendation** - matches place categories against trip interests (with a related-interest map).
6. **Weighted Scoring** - combines interest match (40), rating (25), budget fit (20), weather (15) into one explainable score.
7. **Weather Suitability** - condition + temperature -> 0-100 suitability for outdoor/indoor activities; powers replanning.
8. **Expense Settlement (minimum cash flow)** - Splitwise-style greedy matching of largest debtor and creditor.

## 8. Installation (fresh Windows machine)

### Step 0 - Install required software
1. **Python 3.10+** from python.org - tick *Add python.exe to PATH* during install. Verify: `python --version`
2. **Git** from git-scm.com. Verify: `git --version`
3. **MySQL Server + MySQL Workbench** from dev.mysql.com (remember the root password you set).
4. **VS Code** from code.visualstudio.com.

### Step 1 - Create the database
Open MySQL Workbench, connect as root, run:

    CREATE DATABASE smarttrip_db CHARACTER SET utf8mb4;

### Step 2 - Extract and open the project
Extract the ZIP to e.g. `C:\Users\<you>\Desktop\SmartTripAI` and open that folder in VS Code (File > Open Folder). Open a terminal (Terminal > New Terminal).

### Step 3 - Virtual environment

    python -m venv venv
    venv\Scripts\activate

Your prompt should now start with `(venv)` - that is how you know it is active.
If PowerShell blocks activation, run `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser` and retry.

### Step 4 - Install dependencies

    pip install -r requirements.txt

### Step 5 - Environment variables (API keys live here)
Copy `.env.example` to `.env` (same folder as manage.py) and edit it:

| Variable | Meaning |
|----------|---------|
| SECRET_KEY | Any long random string for Django |
| DEBUG | True for development |
| ALLOWED_HOSTS | localhost,127.0.0.1 |
| DB_ENGINE | mysql (or sqlite for a quick demo without MySQL) |
| DB_NAME / DB_USER / DB_PASSWORD / DB_HOST / DB_PORT | Your MySQL credentials |
| OPENWEATHER_API_KEY | **Optional** free key from openweathermap.org for live forecasts. Leave empty to use built-in demo weather. |
| CURRENCY_API_URL | Keyless currency endpoint (leave the default) |

**The `.env` file is the ONLY place API keys are entered.** The app is fully functional with no keys - weather and currency fall back to built-in demo data automatically.

### Step 6 - Migrate, seed, admin, run

    python manage.py makemigrations
    python manage.py migrate
    python manage.py seed_data
    python manage.py createsuperuser
    python manage.py runserver

Open http://127.0.0.1:8000/ (site) and http://127.0.0.1:8000/admin/ (admin dashboard).

## 9. Testing

Run the automated suite (algorithm unit tests + auth/privacy/flow tests):

    python manage.py test

Manual flow: Register -> Login -> Dashboard -> Create trip (destination, dates, budget, interests) -> Itinerary > Generate Smart Itinerary (K-Means + TSP) -> Recommendations > Generate (content-based + weighted + weather) -> Map (TSP optimize, Dijkstra path) -> Budget (knapsack) -> Group > invite member -> Voting > create poll and vote -> Expenses > add and check settlement -> Weather > Smart Replan -> Assistant -> Checklist -> Journal -> Analytics (charts + trip score) -> Admin panel.

With Postman you can exercise the same URLs (session authentication: log in via /login/ first and reuse the cookies).

## 10. Troubleshooting

| Problem | Cause | Fix |
|---------|-------|-----|
| `python` not recognized | Python not on PATH | Reinstall Python with *Add to PATH*, reopen the terminal |
| `pip` not recognized | venv not active / PATH | Activate the venv: `venv\Scripts\activate` |
| Activation error in PowerShell | Execution policy | `Set-ExecutionPolicy RemoteSigned -Scope CurrentUser` |
| mysqlclient install fails | Missing build tools | `pip install mysqlclient` usually ships wheels; else install "Microsoft C++ Build Tools", or set `DB_ENGINE=sqlite` temporarily |
| Access denied for user | Wrong DB_USER/DB_PASSWORD in .env | Fix credentials; ensure the MySQL service is running |
| Unknown database 'smarttrip_db' | DB not created | Run the CREATE DATABASE statement in Workbench |
| Migration errors | Stale partial state | Drop and recreate the database, rerun both migration commands |
| No module named X | Dependencies missing | Activate the venv, `pip install -r requirements.txt` |
| TemplateDoesNotExist | Wrong working directory | Run manage.py from the project root (the folder containing manage.py) |
| CSS/JS not loading | Static misconfig / cache | Hard refresh (Ctrl+F5); ensure DEBUG=True in development |
| 404 error | Wrong URL | Check the navbar links; all URLs are defined in core/urls.py |
| Port already in use | Another server on 8000 | `python manage.py runserver 8001` |
| Weather always the same | No API key | That is the demo fallback; add OPENWEATHER_API_KEY to .env for live data |
| Map tiles blank | No internet / blocked CDN | Leaflet loads tiles from openstreetmap.org; check connectivity |

## 11. GitHub Setup

`.gitignore` already excludes venv/, __pycache__/, .env, db.sqlite3, media/ and IDE files.

    git init                                          # start a repository in this folder
    git add .                                         # stage every project file
    git commit -m "Initial SmartTrip AI project"      # first snapshot
    git branch -M main                                # name the branch main
    git remote add origin YOUR_GITHUB_REPOSITORY_URL  # link your empty GitHub repo
    git push -u origin main                           # upload and set the upstream

## 12. Deployment Notes

For a simple production deployment: set `DEBUG=False`, add your domain to `ALLOWED_HOSTS`, set a strong `SECRET_KEY`, run `python manage.py collectstatic`, and serve with gunicorn/waitress behind Nginx (or use a PaaS like Railway/Render with the same .env variables and a managed MySQL instance).

## 13. Future Scope

Real-time chat, flight/hotel booking API integration, LLM-powered assistant, mobile app on the same backend (DRF), multi-country currency-aware trips, offline PWA mode, and an ML-trained personal preference model.
