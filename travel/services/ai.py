
"""Optional LLM integration with database-backed travel recommendations."""

import json
import os
import re
from datetime import date, timedelta
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


API_URL = os.getenv(
    "OPENAI_BASE_URL",
    "https://api.openai.com/v1/chat/completions",
)

OLLAMA_URL = os.getenv(
    "OLLAMA_BASE_URL",
    "http://127.0.0.1:11434/api/chat",
)


# ---------------------------------------------------------
# OPTIONAL AI PROVIDERS
# ---------------------------------------------------------

def _chat_openai(messages, temperature=0.2, max_tokens=700):
    """Call an OpenAI-compatible chat completion endpoint."""

    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None

    payload = {
        "model": os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    request = Request(
        API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urlopen(request, timeout=45) as response:
            data = json.loads(response.read().decode("utf-8"))

        return data["choices"][0]["message"]["content"].strip()

    except (
        URLError, HTTPError, TimeoutError, ValueError,
        KeyError, IndexError, TypeError,
    ):
        return None


def _chat_ollama(messages, temperature=0.2, max_tokens=700):
    """Use an optional locally running Ollama model."""

    payload = {
        "model": os.getenv("OLLAMA_MODEL", "llama3.2:3b"),
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
        },
    }

    request = Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urlopen(request, timeout=90) as response:
            data = json.loads(response.read().decode("utf-8"))

        return data.get("message", {}).get("content", "").strip() or None

    except (
        URLError, HTTPError, TimeoutError, ValueError,
        KeyError, TypeError,
    ):
        return None


def _chat(messages, temperature=0.2, max_tokens=700):
    """Use the configured provider, with paid fallback opt-in."""

    provider = os.getenv("AI_PROVIDER", "auto").strip().lower()

    if provider == "local":
        return None

    if provider == "ollama":
        return _chat_ollama(messages, temperature, max_tokens)

    if provider == "openai":
        return _chat_openai(messages, temperature, max_tokens)

    answer = _chat_ollama(messages, temperature, max_tokens)
    if answer:
        return answer

    if os.getenv("AI_ALLOW_PAID_FALLBACK", "0").strip() == "1":
        return _chat_openai(messages, temperature, max_tokens)

    return None


# ---------------------------------------------------------
# DATABASE-BACKED TRAVEL RECOMMENDATIONS
# ---------------------------------------------------------

def _database_travel_reply(question):
    """Answer attraction requests using the existing Django database."""

    from travel.models import Destination, Attraction

    # Normalize whitespace and common destination-name typing variations.
    q = (question or "").strip().lower()
    q = re.sub(
        r"\b(in|at|around|near)\s*(bengaluru|bangalore|goa)\b",
        r"\1 \2",
        q,
    )
    q = re.sub(r"\s+", " ", q)

    place_terms = (
        "hidden gem", "hidden gems",
        "places to visit", "places to explore",
        "attractions", "recommend places",
        "suggest places", "show me places",
        "place to visit", "where to visit",
        "things to do", "nature places",
        "nature attractions", "free attractions",
        "free places", "free things to do",
        "historical places", "food places",
    )

    if not any(term in q for term in place_terms):
        return None

    destinations = list(Destination.objects.all())

    if not destinations:
        return "There are no destinations in the database yet."

    # Match a destination by its complete name where possible.
    destination = None

    for item in destinations:
        name = item.name.lower().strip()

        if re.search(rf"(?<!\w){re.escape(name)}(?!\w)", q):
            destination = item
            break

    # Support Bengaluru/Bangalore naming variations.
    if destination is None and (
        "bengaluru" in q or "bangalore" in q
    ):
        destination = next(
            (
                item for item in destinations
                if "bengaluru" in item.name.lower()
                or "bangalore" in item.name.lower()
            ),
            None,
        )

    if destination is None:
        if len(destinations) == 1:
            destination = destinations[0]
        else:
            names = ", ".join(item.name for item in destinations)
            return (
                "Which destination would you like recommendations for?\n"
                f"Available destinations: {names}"
            )

    # Extract the requested result count.
    count_match = re.search(r"\b(\d{1,2})\b", q)
    count = int(count_match.group(1)) if count_match else 3
    count = max(1, min(count, 10))

    attractions = list(
        Attraction.objects.filter(destination=destination)
    )

    if not attractions:
        return f"No attractions are listed for {destination.name} yet."

    def attraction_cost(item):
        value = getattr(item, "estimated_cost", 0) or 0

        try:
            return max(0.0, float(value))
        except (TypeError, ValueError):
            return 0.0

    def searchable_text(item):
        tags = getattr(item, "tags", "") or ""

        if isinstance(tags, (list, tuple, set)):
            tags = " ".join(str(tag) for tag in tags)

        return " ".join(
            str(value or "")
            for value in (
                getattr(item, "name", ""),
                getattr(item, "category", ""),
                getattr(item, "description", ""),
                tags,
            )
        ).lower()

    # Identify strict filters requested by the user.
    free_request = bool(
        re.search(
            r"\bfree\b|\bno[- ]cost\b|\bzero[- ]cost\b",
            q,
        )
    )

    nature_request = bool(
        re.search(r"\bnature\b|\bnatural\b", q)
    )

    hidden_request = bool(
        re.search(r"\bhidden[- ]gems?\b", q)
    )

    # Identify other requested interests.
    interest_terms = {
        "nature": (
            "nature", "park", "garden", "lake",
            "forest", "wildlife", "botanical",
        ),
        "history": (
            "history", "historical", "palace",
            "museum", "heritage", "fort",
        ),
        "food": (
            "food", "restaurant", "cafe",
            "market", "street food",
        ),
        "adventure": (
            "adventure", "trek", "hike",
            "climb", "cycling", "waterfall",
        ),
        "culture": (
            "culture", "temple", "art",
            "craft", "dance",
        ),
        "shopping": (
            "shopping", "mall", "shop",
        ),
        "relaxation": (
            "relax", "peaceful", "quiet", "spa",
        ),
    }

    # Apply strict zero-cost filtering.
    if free_request:
        attractions = [
            item for item in attractions
            if attraction_cost(item) == 0
        ]

    # Apply nature filtering instead of merely ranking nature attractions.
    if nature_request:
        nature_words = interest_terms["nature"]

        attractions = [
            item for item in attractions
            if (
                str(getattr(item, "category", "") or "").lower()
                == "nature"
                or any(
                    term in searchable_text(item)
                    for term in nature_words
                )
            )
        ]

    # Recognize other explicitly requested categories.
    requested_interests = []

    for interest, terms in interest_terms.items():
        if interest == "nature":
            continue

        if any(
            re.search(rf"\b{re.escape(term)}\b", q)
            for term in terms
        ):
            requested_interests.append((interest, terms))

    # Only filter other interests if a category was clearly requested.
    # Nature requests have already been filtered above.
    if requested_interests and not nature_request:
        matched = [
            item for item in attractions
            if any(
                term in searchable_text(item)
                for _, terms in requested_interests
                for term in terms
            )
        ]

        if matched:
            attractions = matched

    if not attractions:
        return (
            f"No attractions in {destination.name} matched "
            "your requested filters. Try another category "
            "or a different destination."
        )

    # Recognize explicit budgets such as "under ₹500" or "budget of 1000".
    budget_match = re.search(
        r"(?:budget(?:\s+of)?|under|within|below|less than|"
        r"₹|rs\.?|inr)\s*"
        r"(?:₹|rs\.?|inr)?\s*([0-9][0-9,]*)",
        q,
    )

    budget = None

    if budget_match:
        budget = float(budget_match.group(1).replace(",", ""))

        affordable = [
            item for item in attractions
            if attraction_cost(item) <= budget
        ]

        # A specified budget is a strict constraint.
        attractions = affordable

    if not attractions:
        return (
            f"No attractions in {destination.name} match "
            "your requested budget and filters."
        )

    def rank(item):
        try:
            hidden_score = float(
                getattr(item, "hidden_gem_score", 0) or 0
            )
        except (TypeError, ValueError):
            hidden_score = 0

        try:
            sustainability = float(
                getattr(item, "sustainability_score", 0) or 0
            )
        except (TypeError, ValueError):
            sustainability = 0

        crowd_value = getattr(item, "crowd_level", 0) or 0

        try:
            crowd_score = float(crowd_value)
        except (TypeError, ValueError):
            crowd_score = 50

        # Lower numeric crowd levels are treated as less crowded.
        low_crowd_score = 100 - max(0, min(100, crowd_score))

        interest_score = 0
        text = searchable_text(item)

        for interest, terms in requested_interests:
            if interest in text or any(term in text for term in terms):
                interest_score += 1

        return (
            hidden_score if hidden_request else 0,
            interest_score,
            sustainability,
            low_crowd_score,
        )

    attractions.sort(key=rank, reverse=True)

    # Remove duplicate names while preserving ranking.
    unique = []
    seen = set()

    for item in attractions:
        name = str(getattr(item, "name", "") or "").strip()

        if name and name.casefold() not in seen:
            unique.append(item)
            seen.add(name.casefold())

    selected = unique[:count]

    if hidden_request:
        heading = (
            f"Here are {len(selected)} hidden-gem suggestions "
            f"in {destination.name}."
        )
    elif free_request:
        heading = (
            f"Here are {len(selected)} free attractions "
            f"in {destination.name}."
        )
    elif nature_request:
        heading = (
            f"Here are {len(selected)} nature places "
            f"in {destination.name}."
        )
    else:
        heading = (
            f"Here are {len(selected)} places to explore "
            f"in {destination.name}."
        )

    lines = [heading]
    total_cost = 0.0

    for index, item in enumerate(selected, start=1):
        cost = attraction_cost(item)
        total_cost += cost

        category = (
            getattr(item, "category", "") or "General"
        )

        description = (
            getattr(item, "description", "")
            or "No description is available yet."
        )

        duration = getattr(item, "duration_hours", None)

        lines.extend([
            "",
            f"{index}. {item.name}",
            f"   Category: {category}",
            f"   Estimated attraction cost: ₹{cost:g}",
            f"   About: {description}",
        ])

        if duration is not None:
            lines.append(f"   Suggested duration: {duration} hours")

    lines.extend([
        "",
        f"Estimated combined attraction cost: ₹{total_cost:g}.",
        "This estimate covers attraction entry costs only; "
        "transport, food, accommodation and other fees may cost extra.",
    ])

    if len(selected) < count:
        lines.extend([
            "",
            f"Note: Only {len(selected)} matching attraction(s) "
            f"are currently available in the database for {destination.name}.",
        ])

    if budget is not None:
        lines.append(
            f"Your attraction budget was ₹{budget:g}; "
            "all listed attractions satisfy that limit."
        )

    return "\n".join(lines)


# ---------------------------------------------------------
# MAIN CHATBOT RESPONSE
# ---------------------------------------------------------

def _is_recommendation_explanation(question):
    q = (question or "").lower()
    asks_for_explanation = any(term in q for term in ("why", "reason", "explain"))
    refers_to_recommendations = any(
        term in q for term in ("recommend", "attraction", "selected", "chosen")
    )
    return asks_for_explanation and refers_to_recommendations


def _trip_recommendation_explanation(context):
    recommendations = context.get("scheduled_recommendations") or []
    if not recommendations:
        if context.get("trip_title"):
            return (
                f"I can see **{context['trip_title']}**, but there are no saved itinerary recommendation details to explain. "
                "Which attraction from the trip would you like to ask about?"
            )
        return (
            "Which trip or destination are you asking about? Open that trip's assistant so I can use its saved "
            "attraction scores and recommendation reasons."
        )

    trip_label = context.get("trip_title") or "your trip"
    destination = context.get("destination")
    location = f" in **{destination}**" if destination else ""
    lines = [f"Saved recommendation details for **{trip_label}**{location}:"]
    for item in recommendations:
        name = str(item.get("name") or "Unnamed attraction")
        line = f"- **{name}**"
        score = item.get("score")
        if score is not None:
            try:
                score_text = f"{float(score):g}"
            except (TypeError, ValueError):
                score_text = None
            if score_text is not None:
                line += f" (stored score: {score_text})"
        reason = str(item.get("reason") or "").strip()
        line += f": {reason}" if reason else ": no recommendation reason is saved for this stop."
        lines.append(line)
    return "\n".join(lines)

def assistant_reply(question, context=None):
    """Answer travel questions using an AI provider or local database."""

    question = (question or "").strip()

    if not question:
        return (
            "Tell me what you need help with, such as destinations, "
            "attractions, budgets or your itinerary.",
            "local",
        )

    context = context or {}

    # Explain the saved trip items before the generic attraction lookup,
    # which does not have the current trip's destination or item details.
    if _is_recommendation_explanation(question):
        return _trip_recommendation_explanation(context), "local"

    # Use database-backed answers first for attraction requests.
    # This ensures strict filters are not bypassed by an LLM response.
    database_answer = _database_travel_reply(question)

    if database_answer:
        return database_answer, "local"

    prompt = (
        "You are SmartTrip AI, a practical travel-planning assistant "
        "inside a Django travel application. Answer clearly, accurately, and briefly. "
        "Ground your answers strictly in the supplied trip and database context. "
        "Do not invent live weather, real-time prices, opening hours, bookings, "
        "or live transport availability. When data is not supplied, say it needs checking locally. "
        "Explain that final itinerary feasibility is verified by the "
        "application's rules-based planner. "
        f"Available trip context: "
        f"{json.dumps(context, ensure_ascii=False, default=str)}"
    )

    answer = _chat([
        {"role": "system", "content": prompt},
        {"role": "user", "content": question},
    ])

    if answer:
        return answer, "llm"

    q = question.lower()

    # Respect grounding guidelines: do not invent live booking/hours/prices
    if any(k in q for k in ("live price", "ticket booking", "book a ticket", "opening hours", "open now", "closing time")):
        return (
            "SmartTrip AI does not invent or look up live ticket booking availability, "
            "real-time pricing, or live venue opening hours. Please check official venue websites "
            "or local booking counters directly.",
            "local",
        )

    trip_title = context.get("trip_title")
    dest_name = context.get("destination")

    if "weather" in q or "rain" in q:
        if dest_name:
            answer = (
                f"SmartTrip monitors weather-adaptive planning for **{dest_name}**. "
                "Each itinerary day displays forecast context. For outdoor attractions, "
                "SmartTrip pre-computes weather-compatible indoor alternatives that you "
                "can swap in using the dynamic replanning tool on your trip details page. "
                "(Live weather relies on the Open-Meteo service; offline mode uses seasonal climate estimates)."
            )
        else:
            answer = (
                "Open a trip itinerary to view the available forecast and "
                "weather-compatible alternatives. Forecast coverage depends "
                "on your travel dates and the weather service."
            )

    elif "budget" in q or "cost" in q or "spend" in q or "money" in q:
        if context.get("budget_inr") is not None and context.get("estimated_cost_inr") is not None:
            budget = context["budget_inr"]
            estimated = context["estimated_cost_inr"]
            days = context.get("days", 1)
            travelers = context.get("travelers", 1)
            diff = budget - estimated
            if diff >= 0:
                status = f"Your itinerary fits within budget with an estimated buffer of ₹{diff:,}."
            else:
                status = f"Your estimated spend exceeds your budget by ₹{abs(diff):,}. Try reducing duration or swapping paid stops in What-if Planning."

            answer = (
                f"Budget guidance for **{trip_title or 'your trip'}** in {dest_name or 'your destination'}:\n"
                f"• Configured Total Budget: ₹{budget:,}\n"
                f"• Estimated Total Spend: ₹{estimated:,} (~₹{estimated // max(1, days):,}/day for {travelers} traveler(s))\n"
                f"• Status: {status}\n"
                "Visit your trip's Budget page to log itemized expenses and inspect category breakdowns."
            )
        else:
            answer = (
                "Open Budget on your trip to record expenses and review "
                "the estimated total. The feasibility checker flags plans "
                "whose estimated cost exceeds your budget."
            )

    elif "why" in q or "recommend" in q or "suggest" in q or "explain" in q:
        if dest_name and context.get("scheduled_activities"):
            interest = context.get("interest", "your chosen theme")
            activities = context.get("scheduled_activities", [])
            preview = ", ".join(activities[:3])
            answer = (
                f"SmartTrip selected attractions for **{dest_name}** tailored to your interest in **{interest}** "
                f"with {context.get('pace', 'balanced')} pacing. Recommendation scoring balances your category preferences, "
                f"sustainability scores, hidden-gem uniqueness, and crowd ratings. "
                f"Your itinerary highlights include: {preview}. Click on any stop in your itinerary to read its specific recommendation reason."
            )
        else:
            answer = (
                "SmartTrip ranks attractions using your interests, feedback, "
                "hidden-gem potential, sustainability and crowd levels. "
                "Open an itinerary item to see its recommendation explanation."
            )

    elif "alternative" in q or "what if" in q or "change" in q or "replan" in q or "swap" in q:
        if dest_name:
            answer = (
                f"To explore alternatives for your **{dest_name}** trip:\n"
                "1. **Decision Lab:** Compare multi-objective NSGA-II Pareto alternatives and 0/1 Knapsack attraction bundles.\n"
                "2. **What-if Planning:** Test budget adjustments or extra days without altering your saved trip.\n"
                "3. **Dynamic Replanning:** Swap weather-affected stops with indoor backups while preserving unaffected activities."
            )
        else:
            answer = (
                "Use What-if Planning to test budget or duration changes. "
                "Weather-aware replanning evaluates alternatives while "
                "the itinerary repair engine aims to preserve unaffected activities."
            )

    elif "route" in q or "map" in q or "distance" in q or "travel time" in q:
        answer = (
            "Open your trip details to view the interactive Leaflet map. "
            "Stops are sequenced using 2-opt route optimization to minimize travel distance. "
            "Driving distance and durations are estimated via OSRM when online, with straight-line geographic connections as fallback."
        )

    elif "group" in q:
        answer = (
            "Group Planning combines member preference signals to help "
            "create a plan around shared interests."
        )

    elif "destination" in q or "visit" in q or "place" in q:
        from travel.models import Destination
        dest_list = list(Destination.objects.all()[:6])
        if dest_list:
            names = ", ".join(f"{d.name} (from ₹{d.average_daily_cost}/day)" for d in dest_list)
            answer = (
                f"SmartTrip has destinations ready to explore, including: {names}. "
                "Browse Destinations to view attraction categories, ratings, and sustainability scores."
            )
        else:
            answer = (
                "Explore Destinations to compare available places, attraction "
                "categories, ratings, estimated costs and sustainability information."
            )

    elif len(q) < 4:
        answer = (
            "Please ask a travel question about destinations, attractions, budgets, "
            "itinerary explanations, weather backups, or trip changes."
        )

    else:
        answer = (
            "I can help with destinations, personalized recommendations, "
            "route maps, weather-aware alternatives, budgets, group trips "
            "and itinerary changes. Ask me about one of these topics, or "
            "configure an AI provider for conversational LLM responses."
        )

    return answer, "local"


# ---------------------------------------------------------
# STRUCTURED TRIP REQUEST INTERPRETATION
# ---------------------------------------------------------

def interpret_trip_request(text, destinations):
    """Extract trip preferences with an optional LLM fallback."""

    text = (text or "").strip()

    destination_names = [
        str(destination.get("name", ""))
        for destination in destinations
    ]

    system = (
        "Extract a travel request into JSON only. Keys: destination, "
        "title, days, budget, travelers, interest, pace, start_date. "
        "destination must exactly match one provided destination or be empty. "
        "interest must be one of culture,nature,adventure,food,history,"
        "shopping,relaxation. pace must be relaxed,balanced,packed. "
        "Use null for unknown numbers/dates. Do not invent a date."
    )

    llm = _chat([
        {"role": "system", "content": system},
        {
            "role": "user",
            "content": (
                f"Available destinations: {destination_names}. "
                f"Request: {text}"
            ),
        },
    ], temperature=0, max_tokens=350)

    result = {}

    if llm:
        try:
            match = re.search(r"\{.*\}", llm, re.S)
            if match:
                result = json.loads(match.group(0))
        except (ValueError, TypeError):
            result = {}

    low = text.lower()

    if not result.get("destination"):
        result["destination"] = next(
            (
                name for name in destination_names
                if name.lower() in low
            ),
            "",
        )

    if not result.get("budget"):
        money = re.search(
            r"(?:budget(?:\s+of)?|under|within|rupees|rs\.?|inr|₹)"
            r"\s*(?:₹|rs\.?|inr)?\s*"
            r"([0-9][0-9,]*)\s*(k|thousand)?",
            low,
        )

        if money:
            amount = int(money.group(1).replace(",", ""))
            multiplier = (
                1000 if money.group(2) in {"k", "thousand"} else 1
            )
            result["budget"] = amount * multiplier

    if not result.get("days"):
        match = re.search(r"(\d+)\s*[- ]?day", low)
        result["days"] = (
            int(match.group(1))
            if match
            else (2 if "weekend" in low else 3)
        )

    if not result.get("travelers"):
        match = re.search(
            r"(\d+)\s*(?:trave[l]{1,2}ers?|people|persons?|friends|adults?|members?)",
            low,
        )
        result["travelers"] = int(match.group(1)) if match else 1

    if not result.get("interest"):
        result["interest"] = next(
            (
                interest
                for interest in (
                    "nature", "adventure", "food", "history",
                    "shopping", "relaxation", "culture",
                )
                if interest in low
            ),
            "culture",
        )

    if result.get("pace") not in {"relaxed", "balanced", "packed"}:
        if any(w in low for w in ["relaxed", "slow", "unhurried", "chill", "leisurely"]):
            result["pace"] = "relaxed"
        elif any(w in low for w in ["packed", "fast", "hectic", "busy", "action"]):
            result["pace"] = "packed"
        else:
            result["pace"] = "balanced"

    if any(w in low for w in ["hidden gem", "off beat", "less crowd", "less-crowded", "peaceful", "secret"]):
        result["include_hidden_gems"] = True

    try:
        result["days"] = max(1, min(30, int(result.get("days") or 3)))
    except (ValueError, TypeError):
        result["days"] = 3

    try:
        result["budget"] = max(
            0,
            int(str(result.get("budget") or 10000).replace(",", "")),
        )
    except (ValueError, TypeError):
        result["budget"] = 10000

    try:
        result["travelers"] = max(
            1,
            min(50, int(result.get("travelers") or 1)),
        )
    except (ValueError, TypeError):
        result["travelers"] = 1

    try:
        start = date.fromisoformat(str(result.get("start_date")))
        if start < date.today():
            start = date.today()
    except (ValueError, TypeError):
        start = date.today() + timedelta(days=7)

    result["start_date"] = start.isoformat()
    result["end_date"] = (
        start + timedelta(days=result["days"] - 1)
    ).isoformat()

    if not result.get("title"):
        result["title"] = (
            f"{result.get('destination') or 'My'} "
            f"{result['days']}-day trip"
        )

    result["source"] = "llm" if llm else "local"

    return result
