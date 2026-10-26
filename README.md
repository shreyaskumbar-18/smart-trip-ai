# SmartTrip AI, Final Integrated Version

SmartTrip AI is a Django-based intelligent travel planning and tourism management system. It combines destination discovery, personalized recommendations, itinerary optimization, budgeting, weather-aware replanning, group planning, reviews, ratings and a context-aware travel assistant in one application.

## Final feature set

- Email OTP verification during registration
- Password login after verified account activation
- Passwordless email OTP login
- Email OTP password reset
- User profile and learned preference profile
- Destination search and filters
- Destination comparison
- Attractions and hidden-gem discovery
- Sustainability scoring
- Reviews and 1 to 5 star ratings
- Helpful review feedback
- Personalized recommendation scoring
- Feedback-based preference learning
- Explainable recommendations
- Multi-day itinerary generation
- Pace-aware itinerary optimization
- Geographic route ordering using nearest-neighbour with 2-opt local improvement
- Graph shortest-path utilities: Dijkstra and A* on a geographic proximity graph
- Geographic DBSCAN attraction clustering with category fallback
- Group preference aggregation that balances average and minimum member satisfaction
- 0/1 Knapsack budget-aware attraction selection in Decision Lab
- NSGA-II Pareto optimization for alternative itinerary trade-offs
- Feasibility checking
- Weather-aware alternatives and dynamic replanning
- What-if trip scenarios
- Budget and expense tracking
- Group trips and group preference optimization
- Saved trips
- Interactive Leaflet map with numbered itinerary stops
- OSRM road-route estimates with straight-line fallback
- Live Open-Meteo weather when coordinates and forecast dates are available, clearly labelled offline fallback otherwise
- Natural-language trip brief parsing with optional LLM API support
- LLM-assisted SmartTrip AI chat when an API key is configured, with local fallback
- Minimum-disruption itinerary repair that preserves unaffected activities
- Dedicated SmartTrip AI assistant page (no floating navigation bot)
- PDF itinerary export
- Admin analytics dashboard
- Django admin
- Automated tests
- Responsive commercial-style travel UI
- Dark mode
- Mobile navigation
- Loading, empty and form states
- Django migrations, MySQL configuration and seeded demo data

## Run on Windows with MySQL (default)

The package uses MySQL as its primary database and defaults to the existing database name `smarttrip`. The setup SQL only creates the database if it does not exist. It does not drop or erase tables. Back up your database before running migrations, and verify the migration history before changing code on an existing installation.

1. Open MySQL Workbench and connect to your local server, or open a terminal where the MySQL client is available.
2. Run `database/create_mysql_database.sql`. It creates `smarttrip` only if it does not exist.
3. Copy `.env.example` to `.env`. Enter your existing MySQL username and password. Keep `DB_NAME=smarttrip` to target the database you previously used.
4. Configure SMTP values in `.env` before testing email OTP. Do not share the `.env` file or include it in your submission.
5. Double-click `START_HERE.bat`. It creates a virtual environment, installs dependencies, runs migrations, seeds sample data, checks Django and starts the server.

Important: inspect your existing migration history and take a MySQL backup before running migrations. The ZIP contains source code and migrations, not your database records. It does not include `db.sqlite3`, a database dump, your virtual environment or a private `.env` file.

Manual setup steps are:

```powershell
python -m venv venv
venv\Scripts\activate
copy .env.example .env
pip install -r requirements.txt
python manage.py migrate
python manage.py seed_data
python manage.py check
python manage.py test
python manage.py runserver
```

Open:

```text
http://127.0.0.1:8000/
```

## OTP email

The example configuration uses SMTP and requires valid provider credentials. Email delivery has not been verified from this package because your private SMTP credentials are not included. Configure these values in `.env`:

```text
EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend
EMAIL_HOST=smtp.gmail.com
EMAIL_PORT=587
EMAIL_HOST_USER=your_email
EMAIL_HOST_PASSWORD=your_app_password
EMAIL_USE_TLS=1
DEFAULT_FROM_EMAIL=SmartTrip AI <your_email>
```

Use an SMTP provider and an application password where required.

## MySQL configuration

MySQL is the default database. The example `.env` settings are:

```text
DB_ENGINE=mysql
DB_NAME=smarttrip
DB_USER=root
DB_PASSWORD=your_password
DB_HOST=127.0.0.1
DB_PORT=3306
```

PyMySQL is included in requirements for Windows compatibility. Create the database with `database/create_mysql_database.sql`, confirm the target is `smarttrip`, then run:

```powershell
python manage.py migrate
python manage.py seed_data
```

The application uses one canonical Django database configuration. The `database/` folder contains a backup SQL export of the supplied consolidated SQLite database.

## Authentication flow

```text
Registration
    ↓
Email OTP
    ↓
Verify
    ↓
Account activation
    ↓
Login
```

Alternative:

```text
Email
 ↓
OTP
 ↓
Passwordless login
```

Password recovery:

```text
Email
 ↓
Reset OTP
 ↓
New password
```

## Recommendation workflow

```text
Profile interests
       +
Trip preferences
       +
Previous feedback
       +
Learned preference profile
       +
Sustainability
       +
Hidden-gem score
       +
Crowd pressure
       ↓
Explainable recommendation score
       ↓
Itinerary optimizer
       ↓
User feedback
       ↓
Preference profile update
```

## Group planning

Group members contribute learned preference signals. SmartTrip calculates the group's strongest preference and regenerates the itinerary around that consensus while retaining the trip constraints.

## Final project structure

```text
SmartTripAI_End_to_End/
├── manage.py
├── requirements.txt
├── .env.example
├── README.md
├── docs/ALGORITHMS.md
├── database/
├── smarttrip/
└── travel/
    ├── models.py
    ├── forms.py
    ├── views.py
    ├── admin.py
    ├── services/
    ├── migrations/
    ├── management/
    ├── templates/
    ├── static/
    └── tests.py
```

## Notes

The weather service queries Open-Meteo when destination attraction coordinates are available and network access works. It labels offline demonstration conditions when live weather is unavailable. The AI assistant and natural-language trip interpreter use an LLM only when OPENAI_API_KEY is configured. Without a key, local fallback behavior keeps the application usable and does not claim a generative response. OSRM route estimates require network access and are labelled as estimates, not traffic-aware navigation.

The seed data command creates the demo destination and attraction dataset. The final ZIP excludes the local SQLite database, database dumps, virtual environment, bytecode caches, and private `.env` file. Django migrations remain included.


## Zero-cost submission configuration

The default configuration uses MySQL, no paid LLM key, SMTP email settings supplied through `.env`, and deterministic local fallback behavior. Email OTP requires valid SMTP credentials and has not been verified against your private email account from this environment. SQLite remains available as an optional local fallback by setting `DB_ENGINE=sqlite` in `.env`. Leaflet is open source. OpenStreetMap tiles, the public OSRM demo, and Open-Meteo are external public services with their own attribution, fair-use, and availability limits. Internet-connected features depend on those services; the core app still starts without them. Do not use public demo endpoints for high-volume production traffic.

## Route map and live weather

- The trip detail page maps all itinerary attractions with known coordinates and numbers them in itinerary order.
- The browser requests an OSRM road route. If the routing service is unavailable, it draws a dashed straight-line connection instead.
- Open-Meteo is queried for current conditions and available daily forecasts. Forecasts outside the provider's available window are not fabricated.
- The public demo APIs require internet access. The project remains usable when they are unavailable.

## Natural-language AI

### Zero-cost local AI (recommended for college submission)

The app does not require a paid API key. Its deterministic local assistant and trip-brief parser work without an LLM. The default `AI_PROVIDER=auto` tries local Ollama and never calls a paid API unless `AI_ALLOW_PAID_FALLBACK=1` is explicitly enabled. For generative responses without per-request API charges, install [Ollama](https://ollama.com/) and run these commands in a terminal:

```powershell
ollama pull llama3.2:3b
ollama run llama3.2:3b
```

Keep Ollama running, then set the following in `.env`:

```text
AI_PROVIDER=ollama
OLLAMA_BASE_URL=http://127.0.0.1:11434/api/chat
OLLAMA_MODEL=llama3.2:3b
```

Ollama and the model run on your computer. Model download size and response speed depend on your hardware and internet connection. If Ollama is not installed or running, the app's local fallback remains available.

### Optional hosted AI

If you choose to configure `OPENAI_API_KEY`, set `AI_PROVIDER=openai` to use the hosted OpenAI API. Hosted API usage is billed separately and is not required for the college demonstration. Keep API keys out of source control. The app validates extracted fields and uses Django's itinerary engine for final planning.

## Research contribution

The repair service aims to preserve existing itinerary items unless the disruption justifies a replacement. Evaluate it against full regeneration using feasibility rate, number of changed activities, route distance, budget violations and preference retention. Treat the algorithm as a proposed contribution until experiments and literature review establish the results and novelty.

## Algorithm and verification notes

- See `docs/ALGORITHMS.md` for algorithm objectives, formulas, complexity notes, and data limitations.
- See `docs/IMPLEMENTATION_STATUS.md` for implemented features, setup requirements, and unverified external dependencies.
- See `docs/TEST_RESULTS.md` for the exact checks and tests run during this upgrade.
