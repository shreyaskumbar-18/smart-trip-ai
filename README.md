# SmartTrip AI

SmartTrip AI is a Django-based intelligent travel planning and tourism management system for personalized itinerary generation, recommendation, feasibility analysis, budgeting, weather-aware alternatives and travel management.

## Implemented modules

- User registration, login and profile
- Destination discovery and search
- Personalized attraction recommendations
- Explainable recommendation scoring
- Feedback-driven preference learning
- Hidden-gem discovery
- Crowd-aware recommendations
- Sustainability scoring
- Multi-day itinerary generation
- Relaxed, Balanced and Packed travel pace
- Category-aware itinerary diversification
- Geographic route ordering when POI coordinates are available
- POI category clustering
- Weather-aware alternatives
- Deterministic offline weather fallback
- Dynamic itinerary re-planning
- Itinerary quality scoring
- Trip feasibility checks
- Budget and expense tracking
- What-if trip planning
- Saved trips
- Group trip planning
- Rule-based travel assistant
- Django admin support
- Sample destination and attraction data

## Technology

- Python
- Django
- SQLite by default
- Optional MySQL configuration
- HTML5
- CSS3
- Bootstrap
- JavaScript

## Windows setup

Open PowerShell in the project directory.

```powershell
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_data
python manage.py check
python manage.py runserver
```

Open:

```text
http://127.0.0.1:8000/
```

Create an account from Register before creating a trip.

## Existing sample database

The supplied `db.sqlite3` contains the six sample destinations and 24 sample attractions. It contains no user accounts or personal trips.

Running the seed command is safe. It uses `update_or_create` for the sample destinations and attractions.

## Main project flow

```text
User preferences
       ↓
Destination selection
       ↓
Recommendation scoring
       ↓
Preference learning
       ↓
Multi-objective itinerary optimization
       ↓
Daily distribution
       ↓
Geographic route ordering
       ↓
Weather-aware alternatives
       ↓
Feasibility and quality scoring
       ↓
Budget / What-if / Group / Feedback
       ↓
Dynamic re-planning
```

## Research-oriented components

The implementation includes explainable recommendation scoring, sustainability-aware ranking, crowd pressure, hidden-gem preference, feedback-based learning, category clustering, geographic route ordering, feasibility checking, what-if analysis and weather-aware re-planning.

These components support the research direction of context-aware and multi-objective travel itinerary generation.

## MySQL

SQLite is the default so the project runs with minimal setup.

To use MySQL, set:

```text
DB_ENGINE=mysql
DB_NAME=smarttrip
DB_USER=root
DB_PASSWORD=your_password
DB_HOST=127.0.0.1
DB_PORT=3306
```

The MySQL Python driver is not included by default. Install the driver used by your environment before switching the database backend.

## Weather

The project uses an offline deterministic forecast so the complete demonstration works without an API key or external service.

The weather service is isolated in:

```text
travel/services/weather.py
```

A live provider can be connected there later without changing the itinerary data model.

## Important project files

```text
travel/models.py
travel/forms.py
travel/views.py
travel/services/recommendation.py
travel/services/optimizer.py
travel/services/weather.py
travel/services/feasibility.py
travel/services/learning.py
travel/services/sustainability.py
travel/services/poi.py
travel/management/commands/seed_data.py
```

## Submission test checklist

Before the college demonstration:

1. Activate the virtual environment.
2. Run `python manage.py check`.
3. Run `python manage.py migrate`.
4. Run `python manage.py seed_data`.
5. Start the server.
6. Register a test account.
7. Create a Goa trip.
8. Open the generated itinerary.
9. Check quality, sustainability and feasibility.
10. Test Like and Dislike feedback.
11. Run Dynamic Re-plan.
12. Test Budget.
13. Test What-if Planning.
14. Test Group Planning.
15. Test Saved Trips.
16. Test the Travel Assistant.
17. Verify logout and login again.

## Project structure

```text
SmartTripAI_End_to_End/
├── manage.py
├── requirements.txt
├── README.md
├── db.sqlite3
├── smarttrip/
└── travel/
    ├── models.py
    ├── forms.py
    ├── views.py
    ├── services/
    ├── management/
    ├── templates/
    └── static/
```
