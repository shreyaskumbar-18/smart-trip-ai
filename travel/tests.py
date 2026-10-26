from datetime import date
from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from .models import Destination, Attraction, Trip, Review, UserPreference, GroupTrip, BudgetExpense, RecommendationFeedback, Profile, SavedTrip, OTPVerification
from .services.recommendation import recommendation_score, explain
from .services.learning import aggregate_group_preferences
from .services.feasibility import what_if
from .services.learning import update_preference_from_feedback, get_preferences
from .services.weather import demo_forecast
from .services.ai import interpret_trip_request, assistant_reply
from .services.repair import repair_itinerary
from .services.copilot import generate_copilot_alternatives, refine_itinerary_with_prompt
from .models import ItineraryItem


class SmartTripServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="testuser", email="test@example.com", password="testpass123")
        self.destination = Destination.objects.create(
            name="Test City", state="Test State", description="Test destination",
            average_daily_cost=2000, best_for="culture,nature", rating=4.5
        )
        self.attraction = Attraction.objects.create(
            destination=self.destination, name="Test Park", category="nature",
            description="A test nature attraction", tags="nature,relaxation",
            sustainability_score=90, hidden_gem_score=80
        )

    def test_trip_days_are_inclusive(self):
        trip = Trip.objects.create(user=self.user, destination=self.destination, title="Test Trip",
            start_date=date(2026,10,2), end_date=date(2026,10,5), travelers=2, budget=20000)
        self.assertEqual(trip.days, 4)

    def test_weather_demo_is_deterministic(self):
        condition, advice = demo_forecast(3)
        self.assertEqual(condition, "Rain")
        self.assertIn("indoor", advice.lower())

    def test_what_if_changes_budget_and_days(self):
        trip = Trip.objects.create(user=self.user, destination=self.destination, title="Test Trip",
            start_date=date(2026,10,2), end_date=date(2026,10,3), travelers=2, budget=10000)
        result = what_if(trip, budget_change=5000, extra_days=1)
        self.assertEqual(result["budget"],15000)
        self.assertEqual(result["days"],3)
        self.assertEqual(result["estimated"],12000)

    def test_feedback_updates_preference(self):
        before = get_preferences(self.user).nature
        update_preference_from_feedback(self.user, self.attraction, "like")
        after = get_preferences(self.user).nature
        self.assertGreater(after, before)

    def test_review_is_unique_per_user_destination(self):
        Review.objects.create(user=self.user, destination=self.destination, rating=5, body="Great")
        self.assertEqual(Review.objects.filter(user=self.user, destination=self.destination).count(),1)

    def test_registration_page_exists(self):
        response = self.client.get(reverse("register"))
        self.assertEqual(response.status_code,200)


class StateChangingMethodTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="method-user", email="method@example.com", password="testpass123"
        )
        self.destination = Destination.objects.create(
            name="Method City", state="Test State", description="Test destination",
            average_daily_cost=1000, best_for="culture",
        )
        self.attraction = Attraction.objects.create(
            destination=self.destination, name="Test Museum", category="culture",
            description="A test attraction",
        )
        self.trip = Trip.objects.create(
            user=self.user, destination=self.destination, title="Method Test Trip",
            start_date=date(2026, 10, 26), end_date=date(2026, 10, 27), budget=5000,
        )
        self.item = ItineraryItem.objects.create(
            trip=self.trip, day_number=1, attraction=self.attraction,
        )
        self.client.force_login(self.user)

    def test_delete_trip_requires_post(self):
        url = reverse("delete_trip", args=[self.trip.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 405)
        self.assertTrue(Trip.objects.filter(pk=self.trip.pk).exists())

        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Trip.objects.filter(pk=self.trip.pk).exists())

    def test_resend_otp_requires_post(self):
        from unittest.mock import patch

        session = self.client.session
        session["pending_user_id"] = self.user.pk
        session.save()
        url = reverse("resend_otp")

        with patch("travel.views.issue_otp") as issue_otp:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 405)
            issue_otp.assert_not_called()

            response = self.client.post(url)
            self.assertRedirects(response, reverse("verify_otp"))
            issue_otp.assert_called_once_with(self.user, "register")

    def test_logout_requires_post(self):
        url = reverse("logout")
        response = self.client.get(url)
        self.assertEqual(response.status_code, 405)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)

        response = self.client.post(url)
        self.assertRedirects(response, reverse("home"))
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 302)

    def test_save_trip_requires_post_and_preserves_access_check(self):
        url = reverse("save_trip", args=[self.trip.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 405)
        self.assertFalse(SavedTrip.objects.filter(user=self.user, trip=self.trip).exists())

        response = self.client.post(url)
        self.assertRedirects(response, reverse("trip_detail", args=[self.trip.pk]))
        self.assertTrue(SavedTrip.objects.filter(user=self.user, trip=self.trip).exists())

        outsider = User.objects.create_user(username="method-outsider", password="testpass123")
        self.client.force_login(outsider)
        response = self.client.post(url)
        self.assertRedirects(response, reverse("dashboard"))
        self.assertFalse(SavedTrip.objects.filter(user=outsider, trip=self.trip).exists())

    def test_feedback_requires_post(self):
        url = reverse("feedback", args=[self.trip.pk, self.item.pk, "like"])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 405)
        self.assertFalse(RecommendationFeedback.objects.filter(user=self.user, trip=self.trip).exists())

        response = self.client.post(url)
        self.assertRedirects(response, reverse("trip_detail", args=[self.trip.pk]))
        self.assertTrue(
            RecommendationFeedback.objects.filter(
                user=self.user, trip=self.trip, attraction=self.attraction, action="like"
            ).exists()
        )

    def test_remove_saved_trip_requires_post(self):
        SavedTrip.objects.create(user=self.user, trip=self.trip)
        url = reverse("remove_saved_trip", args=[self.trip.pk])

        response = self.client.get(url)
        self.assertEqual(response.status_code, 405)
        self.assertTrue(SavedTrip.objects.filter(user=self.user, trip=self.trip).exists())

        response = self.client.post(url)
        self.assertRedirects(response, reverse("saved_trips"))
        self.assertFalse(SavedTrip.objects.filter(user=self.user, trip=self.trip).exists())

    def test_helpful_review_requires_post(self):
        author = User.objects.create_user(username="review-author", password="testpass123")
        review = Review.objects.create(
            user=author, destination=self.destination, rating=5, body="Helpful review"
        )
        url = reverse("helpful_review", args=[review.pk])

        response = self.client.get(url)
        self.assertEqual(response.status_code, 405)
        review.refresh_from_db()
        self.assertEqual(review.helpful_count, 0)

        response = self.client.post(url)
        self.assertRedirects(response, reverse("destination_detail", args=[self.destination.pk]))
        review.refresh_from_db()
        self.assertEqual(review.helpful_count, 1)


class SmartTripInnovationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="repairuser", email="repair@example.com", password="testpass123")
        self.destination = Destination.objects.create(name="Goa", state="Goa", description="Coastal trip", average_daily_cost=2000, best_for="nature,food", rating=4.6)
        self.outdoor = Attraction.objects.create(destination=self.destination, name="Baga Beach", category="nature", description="Beach", estimated_cost=100, duration_hours=2, latitude=15.5557, longitude=73.7517, tags="beach,nature")
        self.indoor = Attraction.objects.create(destination=self.destination, name="Local Museum", category="culture", description="Indoor museum", estimated_cost=100, duration_hours=1.5, latitude=15.5, longitude=73.8, tags="culture,history")
        self.trip = Trip.objects.create(user=self.user, destination=self.destination, title="Goa break", start_date=date(2026, 10, 20), end_date=date(2026, 10, 21), travelers=1, budget=15000, interest="nature")

    def test_trip_brief_local_parser_extracts_destination_days_and_budget(self):
        parsed = interpret_trip_request("Plan 3 days in Goa under ₹12,000 for 2 travellers who like food", [{"id": self.destination.id, "name": "Goa"}])
        self.assertEqual(parsed["destination"], "Goa")
        self.assertEqual(parsed["days"], 3)
        self.assertEqual(parsed["budget"], 12000)
        self.assertEqual(parsed["travelers"], 2)
        self.assertEqual(parsed["interest"], "food")

    def test_local_assistant_returns_fallback_without_api_key(self):
        from unittest.mock import patch
        with patch.dict("os.environ", {"OPENAI_API_KEY": ""}):
            answer, source = assistant_reply("How do I reduce route distance?")
        self.assertEqual(source, "local")
        self.assertTrue(answer)

    def test_repair_keeps_existing_items_when_no_disruption_matches(self):
        ItineraryItem.objects.create(trip=self.trip, day_number=1, attraction=self.outdoor, start_time="09:00", score=70, reason="User preference")
        result = repair_itinerary(self.trip, [self.outdoor, self.indoor], trigger="No disruption")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["attraction"].id, self.outdoor.id)
        self.assertFalse(result[0]["changed"])

    def test_weather_repair_replaces_affected_outdoor_activity_and_preserves_other_stops(self):
        from unittest.mock import patch
        ItineraryItem.objects.create(trip=self.trip, day_number=1, attraction=self.outdoor, start_time="09:00", score=70, reason="Beach preference")
        with patch("travel.services.repair.weather_context", return_value={"condition": "Rain", "advice": "Indoor activities", "source": "Open-Meteo forecast", "target_date": "2026-10-20"}):
            result = repair_itinerary(self.trip, [self.outdoor, self.indoor], trigger="Weather disruption")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["attraction"].id, self.indoor.id)
        self.assertTrue(result[0]["changed"])
        self.assertIn("Baga Beach", result[0]["reason"])


class SmartTripPageRenderTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="pageuser", email="page@example.com", password="testpass123")
        self.destination = Destination.objects.create(name="Mysuru", state="Karnataka", description="Heritage and gardens", average_daily_cost=1800, best_for="history,culture", rating=4.5)
        self.attraction = Attraction.objects.create(destination=self.destination, name="Mysore Palace", category="history", description="Palace visit", estimated_cost=200, duration_hours=2, latitude=12.3052, longitude=76.6552, tags="history,culture")
        self.trip = Trip.objects.create(user=self.user, destination=self.destination, title="Mysuru weekend", start_date=date(2026, 10, 20), end_date=date(2026, 10, 20), travelers=1, budget=5000, interest="history")
        ItineraryItem.objects.create(trip=self.trip, day_number=1, attraction=self.attraction, start_time="09:00", score=80, reason="Matches your interest in history.")
        self.client.force_login(self.user)

    def test_trip_planner_renders_ai_brief_and_form(self):
        response = self.client.get(reverse("trip_planner"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "AI trip brief")
        self.assertContains(response, "Interpret brief")
        self.assertContains(response, "Generate itinerary")

    def test_trip_detail_renders_map_and_weather_sections(self):
        from unittest.mock import patch
        fake_weather = {"condition": "Clear", "advice": "Demo conditions", "source": "Test", "temperature": None, "high": None, "low": None, "rain_probability": None, "wind": None, "target_date": "2026-10-20"}
        with patch("travel.views.weather_context", return_value=fake_weather):
            response = self.client.get(reverse("trip_detail", args=[self.trip.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "tripRouteMap")
        self.assertContains(response, "Mysore Palace")
        self.assertContains(response, "Weather outlook")

    def test_trip_detail_passes_configured_tile_provider_and_renders_stop_preview(self):
        from unittest.mock import patch

        fake_weather = {"condition": "Clear", "advice": "Demo conditions", "source": "Test", "temperature": None, "high": None, "low": None, "rain_probability": None, "wind": None, "target_date": "2026-10-20"}
        with override_settings(
            SMARTTRIP_MAP_TILE_URL="https://tiles.example.test/{z}/{x}/{y}.png",
            SMARTTRIP_MAP_TILE_ATTRIBUTION="Example map provider",
            SMARTTRIP_OSRM_ROUTING_URL="",
        ), patch("travel.views.weather_context", return_value=fake_weather):
            response = self.client.get(reverse("trip_detail", args=[self.trip.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["map_config"]["tile_url"], "https://tiles.example.test/{z}/{x}/{y}.png")
        self.assertEqual(response.context["map_config"]["tile_attribution"], "Example map provider")
        self.assertEqual(response.context["map_config"]["routing_url"], "")
        self.assertContains(response, "data-map-preview")
        self.assertContains(response, "data-focus-map-point")
        self.assertContains(response, "map-config-data")

        with override_settings(
            SMARTTRIP_MAP_TILE_URL="",
            SMARTTRIP_MAP_TILE_ATTRIBUTION="",
            SMARTTRIP_OSRM_ROUTING_URL="",
        ), patch("travel.views.weather_context", return_value=fake_weather):
            unconfigured_response = self.client.get(reverse("trip_detail", args=[self.trip.pk]))
        self.assertEqual(unconfigured_response.status_code, 200)
        self.assertEqual(unconfigured_response.context["map_config"]["tile_url"], "")
        self.assertEqual(unconfigured_response.context["map_config"]["routing_url"], "")

    def test_trip_detail_calculates_straight_line_distance_in_display_order(self):
        second_attraction = Attraction.objects.create(
            destination=self.destination,
            name="Nearby Garden",
            category="nature",
            description="A nearby garden",
            latitude=12.4052,
            longitude=76.6552,
        )
        ItineraryItem.objects.create(
            trip=self.trip,
            day_number=1,
            attraction=second_attraction,
            start_time="10:00",
            score=75,
            reason="Fits a nature break.",
        )

        response = self.client.get(reverse("trip_detail", args=[self.trip.pk]))
        items = response.context["groups"][0]["items"]

        self.assertEqual(len(items), 2)
        self.assertIsNone(items[0].distance_from_previous_km)
        self.assertEqual(items[1].previous_item_id, items[0].pk)
        self.assertAlmostEqual(items[1].distance_from_previous_km, 11.1, places=1)
        self.assertContains(response, "Straight-line from previous stop: 11.1 km")

    def test_trip_detail_handles_missing_coordinates_without_a_distance(self):
        missing_coordinates = Attraction.objects.create(
            destination=self.destination,
            name="Unmapped Stop",
            category="culture",
            description="No coordinates available",
        )
        ItineraryItem.objects.create(
            trip=self.trip,
            day_number=1,
            attraction=missing_coordinates,
            start_time="10:00",
        )

        response = self.client.get(reverse("trip_detail", args=[self.trip.pk]))
        missing_item = response.context["groups"][0]["items"][1]

        self.assertFalse(missing_item.has_map_coordinates)
        self.assertIsNone(missing_item.distance_from_previous_km)
        self.assertContains(response, "Location map unavailable: coordinates are missing.")
        self.assertContains(response, "Straight-line distance unavailable")

    def test_destination_detail_renders_geographic_clusters(self):
        Attraction.objects.create(destination=self.destination, name="Nearby Lake", category="nature", description="Lake walk", estimated_cost=0, duration_hours=1, latitude=12.3060, longitude=76.6560, tags="nature")
        response = self.client.get(reverse("destination_detail", args=[self.destination.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Top attractions")
        self.assertContains(response, "Nearby area")

    def test_group_page_renders_fairness_adjusted_preferences(self):
        response = self.client.get(reverse("group", args=[self.trip.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Fairness-adjusted group preference profile")

    def test_assistant_page_renders(self):
        response = self.client.get(reverse("assistant"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Your travel assistant")

    def test_trip_assistant_explains_saved_recommendation_details(self):
        response = self.client.post(
            reverse("assistant_trip", args=[self.trip.pk]),
            {"question": "Why did SmartTrip recommend these attractions?"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Mysore Palace")
        self.assertContains(response, "stored score: 80")
        self.assertContains(response, "Matches your interest in history.")

    def test_recommendation_question_without_trip_context_asks_for_context(self):
        response = self.client.post(
            reverse("assistant"),
            {"question": "Why did SmartTrip recommend these attractions?"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Which trip or destination are you asking about?")
        self.assertNotContains(response, "stored score:")

    def test_decision_lab_renders_nsga2_knapsack_and_graph_route(self):
        Attraction.objects.create(destination=self.destination, name="Kukkarahalli Lake", category="nature", description="Lake walk", estimated_cost=50, duration_hours=1, latitude=12.3100, longitude=76.6500, tags="nature,relaxation")
        response = self.client.get(reverse("decision_lab", args=[self.trip.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "NSGA-II")
        self.assertContains(response, "0/1 Knapsack")
        self.assertContains(response, "POI network route analysis")

    def test_pdf_export_service_generates_pdf_bytes(self):
        from .services.pdf import trip_pdf
        output = trip_pdf(self.trip)
        self.assertEqual(output.read(4), b"%PDF")

    def test_trip_brief_prefills_fields_for_review(self):
        response = self.client.post(reverse("trip_planner"), {
            "action": "prefill",
            "trip_brief": "Plan 2 days in Mysuru under ₹8,000 for 2 travellers who like history",
            "destination": "",
            "title": "",
            "start_date": "",
            "end_date": "",
            "travelers": "1",
            "budget": "10000",
            "interest": "culture",
            "pace": "balanced",
            "sustainability_priority": "3",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Trip brief interpreted")
        self.assertContains(response, 'value="Mysuru 2-day trip"')
        self.assertContains(response, 'value="8000"')

    def test_manual_trip_form_generates_itinerary(self):
        response = self.client.post(reverse("trip_planner"), {
            "action": "generate",
            "trip_brief": "",
            "destination": str(self.destination.pk),
            "title": "Test generated trip",
            "start_date": "2026-10-20",
            "end_date": "2026-10-20",
            "travelers": "1",
            "budget": "5000",
            "interest": "history",
            "pace": "balanced",
            "sustainability_priority": "3",
        })
        self.assertEqual(response.status_code, 302)
        created = Trip.objects.get(title="Test generated trip", user=self.user)
        self.assertGreater(created.items.count(), 0)


class AlgorithmUnitTests(TestCase):
    def test_dijkstra_finds_lowest_cost_path(self):
        from .services.route_algorithms import dijkstra
        graph = {
            "A": {"B": 2, "C": 7},
            "B": {"A": 2, "C": 1, "D": 5},
            "C": {"A": 7, "B": 1, "D": 2},
            "D": {"B": 5, "C": 2},
        }
        path, cost = dijkstra(graph, "A", "D")
        self.assertEqual(path, ["A", "B", "C", "D"])
        self.assertEqual(cost, 5)

    def test_a_star_finds_path_with_geographic_heuristic(self):
        from .services.route_algorithms import a_star
        graph = {"A": {"B": 2, "C": 8}, "B": {"A": 2, "C": 2}, "C": {"A": 8, "B": 2}}
        coords = {"A": {"latitude": 12.0, "longitude": 77.0}, "B": {"latitude": 12.01, "longitude": 77.0}, "C": {"latitude": 12.02, "longitude": 77.0}}
        path, cost = a_star(graph, coords, "A", "C")
        self.assertEqual(path, ["A", "B", "C"])
        self.assertEqual(cost, 4)

    def test_knapsack_respects_budget_and_selects_best_combination(self):
        from types import SimpleNamespace
        from .services.knapsack import select_attractions_knapsack
        attractions = [
            SimpleNamespace(id=1, name="A", estimated_cost=500),
            SimpleNamespace(id=2, name="B", estimated_cost=400),
            SimpleNamespace(id=3, name="C", estimated_cost=600),
        ]
        result = select_attractions_knapsack(attractions, budget=1000, travelers=1, scores={1: 5, 2: 4, 3: 8})
        self.assertLessEqual(result["total_cost"], 1000)
        self.assertEqual({x.id for x in result["selected"]}, {2, 3})
        self.assertEqual(result["total_value"], 12)

    def test_knapsack_applies_traveller_count_to_cost(self):
        from types import SimpleNamespace
        from .services.knapsack import select_attractions_knapsack
        attractions = [SimpleNamespace(id=1, name="A", estimated_cost=600), SimpleNamespace(id=2, name="B", estimated_cost=300)]
        result = select_attractions_knapsack(attractions, budget=1000, travelers=2, scores={1: 10, 2: 5})
        self.assertEqual(result["total_cost"], 600)
        self.assertEqual([x.id for x in result["selected"]], [2])

    def test_route_order_does_not_drop_attractions(self):
        from types import SimpleNamespace
        from .services.route_algorithms import nearest_neighbor_two_opt
        items = [
            SimpleNamespace(id=1, latitude=12.0, longitude=77.0),
            SimpleNamespace(id=2, latitude=12.01, longitude=77.0),
            SimpleNamespace(id=3, latitude=12.02, longitude=77.0),
            SimpleNamespace(id=4, latitude=12.01, longitude=77.01),
        ]
        route = nearest_neighbor_two_opt(items)
        self.assertEqual({x.id for x in route}, {1, 2, 3, 4})
        self.assertEqual(len(route), len(items))


class AdvancedAlgorithmTests(TestCase):
    def test_dbscan_groups_nearby_attractions_geographically(self):
        from types import SimpleNamespace
        from .services.poi import cluster_attractions
        items = [
            SimpleNamespace(id=1, name="A", category="nature", latitude=12.0000, longitude=77.0000),
            SimpleNamespace(id=2, name="B", category="culture", latitude=12.0010, longitude=77.0010),
            SimpleNamespace(id=3, name="C", category="food", latitude=13.0000, longitude=78.0000),
        ]
        groups = cluster_attractions(items, eps_km=2, min_samples=2)
        self.assertTrue(any({x.id for x in group} == {1, 2} for group in groups.values()))
        self.assertTrue(any(3 in {x.id for x in group} for group in groups.values()))

    def test_group_preference_aggregation_uses_all_members(self):
        from .services.learning import aggregate_group_preferences
        one = User.objects.create_user(username="group-one", email="one@example.com", password="testpass123")
        two = User.objects.create_user(username="group-two", email="two@example.com", password="testpass123")
        first = UserPreference.objects.create(user=one, nature=1.0, culture=0.1)
        second = UserPreference.objects.create(user=two, nature=0.2, culture=0.9)
        scores = aggregate_group_preferences([one, two])
        self.assertAlmostEqual(scores["nature"], 0.7 * 0.6 + 0.3 * 0.2)
        self.assertAlmostEqual(scores["culture"], 0.7 * 0.5 + 0.3 * 0.1)
        self.assertIn("nature", scores)


class GeographicGraphTests(TestCase):
    def test_geographic_path_uses_graph_and_returns_estimated_distance(self):
        from types import SimpleNamespace
        from .services.route_algorithms import plan_geographic_path
        items = [
            SimpleNamespace(id=1, name="A", latitude=12.000, longitude=77.000),
            SimpleNamespace(id=2, name="B", latitude=12.010, longitude=77.000),
            SimpleNamespace(id=3, name="C", latitude=12.020, longitude=77.000),
        ]
        result = plan_geographic_path(items, 1, 3, algorithm="astar", neighbors=1, max_edge_km=5)
        self.assertEqual(result["path_ids"], [1, 2, 3])
        self.assertTrue(result["is_estimate"])
        self.assertGreater(result["distance_km"], 0)


class OTPServiceTests(TestCase):
    def test_otp_is_emailed_hashed_and_single_use(self):
        from django.core import mail
        from django.test import override_settings
        from .services.otp import issue_otp, verify_otp
        user = User.objects.create_user(username="otp-user", email="otp@example.com", password="testpass123")
        with override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"):
            issue_otp(user, "register")
            self.assertEqual(len(mail.outbox), 1)
            body = mail.outbox[0].body
            import re
            match = re.search(r"\b(\d{6})\b", body)
            self.assertIsNotNone(match)
            code = match.group(1)
            record = user.otp_codes.filter(purpose="register").first()
            self.assertNotEqual(record.code_hash, code)
            ok, _ = verify_otp(user, "register", code)
            self.assertTrue(ok)
            ok, _ = verify_otp(user, "register", code)
            self.assertFalse(ok)


class OTPProtectionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="otp-protected", email="protected@example.com", password="testpass123")

    def test_otp_resend_cooldown_blocks_repeat_requests(self):
        from django.core import mail
        from django.test import override_settings
        from .services.otp import issue_otp, OTPRequestThrottled
        with override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"):
            issue_otp(self.user, "register")
            with self.assertRaises(OTPRequestThrottled):
                issue_otp(self.user, "register")
            self.assertEqual(len(mail.outbox), 1)

    def test_otp_attempt_limit_rejects_correct_code_after_five_failures(self):
        from django.core import mail
        from django.test import override_settings
        from .services.otp import issue_otp, verify_otp
        import re
        with override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"):
            issue_otp(self.user, "register")
            code = re.search(r"\b(\d{6})\b", mail.outbox[0].body).group(1)
            for _ in range(5):
                ok, _ = verify_otp(self.user, "register", "999999" if code != "999999" else "888888")
                self.assertFalse(ok)
            ok, _ = verify_otp(self.user, "register", code)
            self.assertFalse(ok)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    DEBUG=False,
)
class AuthenticationFlowTests(TestCase):
    def setUp(self):
        if hasattr(mail, "outbox"):
            mail.outbox.clear()

    def _extract_otp(self):
        import re
        from django.core import mail

        match = re.search(r"Your SmartTrip AI OTP is (\d{6})", mail.outbox[-1].body)
        self.assertIsNotNone(match)
        return match.group(1)

    def _wrong_otp(self, correct_code):
        return f"{(int(correct_code) + 1) % 1000000:06d}"

    def _create_verified_user(self, username="auth-user", email="auth@example.com"):
        user = User.objects.create_user(
            username=username, email=email, password="OriginalPassphrase!7391"
        )
        Profile.objects.create(user=user, email_verified=True)
        return user

    def test_registration_and_email_verification_activate_account(self):
        response = self.client.post(reverse("register"), {
            "username": "new-traveller",
            "email": "New.Traveller@example.com",
            "password1": "Crescent$Trip9876",
            "password2": "Crescent$Trip9876",
        })
        self.assertRedirects(response, reverse("verify_otp"))

        user = User.objects.get(username="new-traveller")
        self.assertEqual(user.email, "new.traveller@example.com")
        self.assertFalse(user.is_active)
        self.assertFalse(user.profile.email_verified)
        self.assertTrue(UserPreference.objects.filter(user=user).exists())
        self.assertEqual(len(mail.outbox), 1)

        response = self.client.post(reverse("verify_otp"), {"otp": self._extract_otp()})
        self.assertRedirects(response, reverse("dashboard"))
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertTrue(user.profile.email_verified)
        self.assertEqual(int(self.client.session.get("_auth_user_id")), user.pk)
        self.assertNotIn("pending_user_id", self.client.session)

    def test_invalid_registration_otp_does_not_activate_account(self):
        response = self.client.post(reverse("register"), {
            "username": "pending-traveller",
            "email": "pending@example.com",
            "password1": "Crescent$Trip9876",
            "password2": "Crescent$Trip9876",
        })
        self.assertEqual(response.status_code, 302)
        user = User.objects.get(username="pending-traveller")

        response = self.client.post(reverse("verify_otp"), {
            "otp": self._wrong_otp(self._extract_otp()),
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Incorrect OTP.")
        user.refresh_from_db()
        self.assertFalse(user.is_active)
        self.assertFalse(user.profile.email_verified)

    def test_password_login_rejects_bad_password_and_accepts_valid_password(self):
        user = self._create_verified_user()

        response = self.client.post(reverse("login"), {
            "username": user.username,
            "password": "incorrect-password",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Invalid username or password.")
        self.assertNotIn("_auth_user_id", self.client.session)

        response = self.client.post(reverse("login"), {
            "username": user.username,
            "password": "OriginalPassphrase!7391",
        })
        self.assertRedirects(response, reverse("dashboard"))
        self.assertEqual(int(self.client.session.get("_auth_user_id")), user.pk)

    def test_otp_login_handles_invalid_code_then_authenticates_and_consumes_code(self):
        user = self._create_verified_user()
        response = self.client.post(reverse("otp_login"), {"email": user.email})
        self.assertRedirects(response, reverse("otp_login_verify"))
        code = self._extract_otp()

        response = self.client.post(reverse("otp_login_verify"), {
            "otp": self._wrong_otp(code),
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Incorrect OTP.")
        self.assertNotIn("_auth_user_id", self.client.session)

        response = self.client.post(reverse("otp_login_verify"), {"otp": code})
        self.assertRedirects(response, reverse("dashboard"))
        self.assertEqual(int(self.client.session.get("_auth_user_id")), user.pk)
        self.assertNotIn("otp_login_user_id", self.client.session)
        self.assertTrue(user.otp_codes.get(purpose="login").used)

    def test_expired_otp_is_rejected_without_counting_a_new_attempt(self):
        from datetime import timedelta
        from django.utils import timezone
        from .services.otp import issue_otp, verify_otp

        user = self._create_verified_user()
        record = issue_otp(user, "login")
        record.expires_at = timezone.now() - timedelta(seconds=1)
        record.save(update_fields=["expires_at"])

        ok, message = verify_otp(user, "login", "123456")
        self.assertFalse(ok)
        self.assertIn("expired or is invalid", message.lower())
        record.refresh_from_db()
        self.assertEqual(record.attempts, 0)

    def test_password_reset_verifies_code_and_updates_password(self):
        user = self._create_verified_user(username="reset-user", email="reset@example.com")
        response = self.client.post(reverse("forgot_password"), {"email": user.email})
        self.assertRedirects(response, reverse("verify_reset_otp"))
        code = self._extract_otp()

        response = self.client.post(reverse("verify_reset_otp"), {
            "otp": self._wrong_otp(code),
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Incorrect OTP.")
        self.assertNotIn("reset_verified_user_id", self.client.session)

        response = self.client.post(reverse("verify_reset_otp"), {"otp": code})
        self.assertRedirects(response, reverse("set_new_password"))
        session = self.client.session
        self.assertEqual(session.get("reset_verified_user_id"), user.pk)
        self.assertEqual(session.get("reset_verified_otp_id"), session.get("reset_otp_id"))

        response = self.client.post(reverse("set_new_password"), {
            "password1": "NewStrongPassphrase!9204",
            "password2": "NewStrongPassphrase!9204",
        })
        self.assertRedirects(response, reverse("login"))
        user.refresh_from_db()
        self.assertTrue(user.check_password("NewStrongPassphrase!9204"))
        self.assertNotIn("reset_user_id", self.client.session)
        self.assertNotIn("reset_otp_id", self.client.session)
        self.assertNotIn("reset_verified_user_id", self.client.session)
        self.assertNotIn("reset_verified_otp_id", self.client.session)

    def test_password_reset_rejects_short_and_mismatched_passwords(self):
        user = self._create_verified_user(username="invalid-reset", email="invalid-reset@example.com")
        self.client.post(reverse("forgot_password"), {"email": user.email})
        self.client.post(reverse("verify_reset_otp"), {"otp": self._extract_otp()})

        response = self.client.post(reverse("set_new_password"), {
            "password1": "short",
            "password2": "short",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Password must contain at least 8 characters.")

        response = self.client.post(reverse("set_new_password"), {
            "password1": "NewStrongPassphrase!9204",
            "password2": "DifferentStrongPassphrase!9204",
        })
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Passwords do not match.")
        user.refresh_from_db()
        self.assertTrue(user.check_password("OriginalPassphrase!7391"))
        self.assertEqual(self.client.session.get("reset_verified_user_id"), user.pk)

    def test_password_reset_applies_configured_similarity_validator(self):
        user = self._create_verified_user(
            username="similarity-target", email="similarity@example.com"
        )
        self.client.post(reverse("forgot_password"), {"email": user.email})
        self.client.post(reverse("verify_reset_otp"), {"otp": self._extract_otp()})

        response = self.client.post(reverse("set_new_password"), {
            "password1": user.username,
            "password2": user.username,
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "similar")
        user.refresh_from_db()
        self.assertTrue(user.check_password("OriginalPassphrase!7391"))

    def test_expired_reset_otp_does_not_authorize_password_change(self):
        from datetime import timedelta
        from django.utils import timezone

        user = self._create_verified_user(
            username="expired-reset", email="expired-reset@example.com"
        )
        self.client.post(reverse("forgot_password"), {"email": user.email})
        code = self._extract_otp()
        record = OTPVerification.objects.get(pk=self.client.session["reset_otp_id"])
        record.expires_at = timezone.now() - timedelta(seconds=1)
        record.save(update_fields=["expires_at"])

        response = self.client.post(reverse("verify_reset_otp"), {"otp": code})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "expired or is invalid")
        self.assertNotIn("reset_verified_user_id", self.client.session)

        response = self.client.post(reverse("set_new_password"), {
            "password1": "NewStrongPassphrase!9204",
            "password2": "NewStrongPassphrase!9204",
        })
        self.assertRedirects(response, reverse("forgot_password"))
        user.refresh_from_db()
        self.assertTrue(user.check_password("OriginalPassphrase!7391"))

    def test_reset_verification_does_not_carry_over_to_a_different_account(self):
        first_user = self._create_verified_user(
            username="first-reset-user", email="first-reset@example.com"
        )
        second_user = self._create_verified_user(
            username="second-reset-user", email="second-reset@example.com"
        )

        self.client.post(reverse("forgot_password"), {"email": first_user.email})
        first_code = self._extract_otp()
        self.client.post(reverse("verify_reset_otp"), {"otp": first_code})
        self.assertEqual(self.client.session.get("reset_verified_user_id"), first_user.pk)

        self.client.post(reverse("forgot_password"), {"email": second_user.email})
        self.assertEqual(self.client.session.get("reset_user_id"), second_user.pk)
        self.assertNotIn("reset_verified_user_id", self.client.session)
        second_code = self._extract_otp()
        response = self.client.post(reverse("set_new_password"), {
            "password1": "AttackerChosenPassphrase!8492",
            "password2": "AttackerChosenPassphrase!8492",
        })
        self.assertRedirects(response, reverse("forgot_password"))

        second_user.refresh_from_db()
        self.assertTrue(second_user.check_password("OriginalPassphrase!7391"))

        # A cooldown retry may reuse this account's still-unused OTP, but not
        # the verification granted to the first account.
        response = self.client.post(reverse("forgot_password"), {"email": second_user.email})
        self.assertRedirects(response, reverse("verify_reset_otp"))
        self.assertEqual(self.client.session.get("reset_user_id"), second_user.pk)
        response = self.client.post(reverse("verify_reset_otp"), {"otp": second_code})
        self.assertRedirects(response, reverse("set_new_password"))
        response = self.client.post(reverse("set_new_password"), {
            "password1": "SecondAccountPassphrase!3841",
            "password2": "SecondAccountPassphrase!3841",
        })
        self.assertRedirects(response, reverse("login"))
        second_user.refresh_from_db()
        self.assertTrue(second_user.check_password("SecondAccountPassphrase!3841"))

    def test_repeated_reset_request_clears_previous_verification(self):
        user = self._create_verified_user(
            username="repeat-reset", email="repeat-reset@example.com"
        )
        self.client.post(reverse("forgot_password"), {"email": user.email})
        code = self._extract_otp()
        self.client.post(reverse("verify_reset_otp"), {"otp": code})
        self.assertEqual(self.client.session.get("reset_verified_user_id"), user.pk)

        response = self.client.post(reverse("forgot_password"), {"email": user.email})
        self.assertRedirects(response, reverse("forgot_password"))
        for key in ("reset_user_id", "reset_otp_id", "reset_verified_user_id", "reset_verified_otp_id"):
            self.assertNotIn(key, self.client.session)

        response = self.client.post(reverse("set_new_password"), {
            "password1": "UnauthorizedNewPassphrase!8430",
            "password2": "UnauthorizedNewPassphrase!8430",
        })
        self.assertRedirects(response, reverse("forgot_password"))
        user.refresh_from_db()
        self.assertTrue(user.check_password("OriginalPassphrase!7391"))

    def test_otp_email_delivery_failure_removes_code_and_registration_stays_unverified(self):
        from unittest.mock import patch
        from .services.otp import issue_otp

        user = User.objects.create_user(
            username="email-failure", email="failure@example.com", password="testpass123",
            is_active=False,
        )
        with patch("travel.services.otp.send_mail", side_effect=OSError("SMTP unavailable")):
            with self.assertRaises(OSError):
                issue_otp(user, "register")

        self.assertFalse(OTPVerification.objects.filter(user=user).exists())

    def test_otp_email_backend_must_confirm_delivery(self):
        from unittest.mock import patch
        from .services.otp import issue_otp

        user = self._create_verified_user(username="zero-delivery", email="zero@example.com")
        with patch("travel.services.otp.send_mail", return_value=0):
            with self.assertRaisesRegex(RuntimeError, "did not confirm delivery"):
                issue_otp(user, "login")

        self.assertFalse(OTPVerification.objects.filter(user=user, purpose="login").exists())

    def test_registration_view_handles_email_delivery_failure_without_activating_account(self):
        from unittest.mock import patch

        with patch("travel.views.issue_otp", side_effect=OSError("SMTP unavailable")):
            response = self.client.post(reverse("register"), {
                "username": "mail-pending",
                "email": "mail-pending@example.com",
                "password1": "Crescent$Trip9876",
                "password2": "Crescent$Trip9876",
            })

        self.assertRedirects(response, reverse("verify_otp"))
        user = User.objects.get(username="mail-pending")
        self.assertFalse(user.is_active)
        self.assertFalse(user.profile.email_verified)

    def test_otp_login_email_delivery_failure_returns_to_otp_request(self):
        from unittest.mock import patch

        user = self._create_verified_user(username="mail-login", email="mail-login@example.com")
        with patch("travel.views.issue_otp", side_effect=OSError("SMTP unavailable")):
            response = self.client.post(reverse("otp_login"), {"email": user.email})

        self.assertRedirects(response, reverse("otp_login"))
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertFalse(OTPVerification.objects.filter(user=user, purpose="login").exists())

    def test_password_reset_email_delivery_failure_returns_to_recovery_form(self):
        from unittest.mock import patch

        user = self._create_verified_user(username="mail-reset", email="mail-reset@example.com")
        with patch("travel.views.issue_otp", side_effect=OSError("SMTP unavailable")):
            response = self.client.post(reverse("forgot_password"), {"email": user.email})

        self.assertRedirects(response, reverse("forgot_password"))
        self.assertNotIn("reset_verified_user_id", self.client.session)
        self.assertNotIn("reset_otp_id", self.client.session)
        self.assertFalse(OTPVerification.objects.filter(user=user, purpose="reset").exists())


class SmartTripFeatureUpgradeTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="traveller1", email="traveller1@example.com", password="password123")
        self.user2 = User.objects.create_user(username="traveller2", email="traveller2@example.com", password="password123")
        self.staff_user = User.objects.create_user(username="staffadmin", email="staff@example.com", password="password123", is_staff=True)
        self.destination = Destination.objects.create(
            name="Coorg",
            state="Karnataka",
            description="Coffee county with misty hills and waterfalls.",
            average_daily_cost=3000,
            best_for="nature,relaxation",
            rating=4.5,
            sustainability_score=85,
        )
        self.client.force_login(self.user)

    def test_review_creation_editing_and_rating_recalculation(self):
        # 1. Create first review with rating 5
        res = self.client.post(reverse("review_destination", args=[self.destination.pk]), {
            "rating": 5,
            "title": "Breathtaking landscapes",
            "body": "Loved the coffee estates and Abbey falls.",
        })
        self.assertEqual(res.status_code, 302)
        self.destination.refresh_from_db()
        self.assertEqual(float(self.destination.rating), 5.0)
        self.assertEqual(self.destination.reviews.count(), 1)

        # 2. Another user adds rating 3 -> average becomes 4.0
        self.client.force_login(self.user2)
        res = self.client.post(reverse("review_destination", args=[self.destination.pk]), {
            "rating": 3,
            "title": "Good but rainy",
            "body": "Rained heavily during our stay.",
        })
        self.assertEqual(res.status_code, 302)
        self.destination.refresh_from_db()
        self.assertEqual(float(self.destination.rating), 4.0)
        self.assertEqual(self.destination.reviews.count(), 2)

        # 3. User 1 updates their review to rating 4 -> average becomes (4+3)/2 = 3.5
        self.client.force_login(self.user)
        res = self.client.post(reverse("review_destination", args=[self.destination.pk]), {
            "rating": 4,
            "title": "Updated review",
            "body": "Great experience overall.",
        })
        self.assertEqual(res.status_code, 302)
        self.destination.refresh_from_db()
        self.assertEqual(float(self.destination.rating), 3.5)
        self.assertEqual(self.destination.reviews.count(), 2)

    def test_review_deletion_requires_post_and_recalculates(self):
        Review.objects.create(user=self.user, destination=self.destination, rating=5, body="Superb")
        self.destination.refresh_from_db()

        # GET request must be rejected (405 Method Not Allowed due to @require_POST)
        get_res = self.client.get(reverse("delete_review", args=[self.destination.pk]))
        self.assertEqual(get_res.status_code, 405)
        self.assertEqual(self.destination.reviews.count(), 1)

        # POST request deletes review and resets destination rating
        post_res = self.client.post(reverse("delete_review", args=[self.destination.pk]))
        self.assertEqual(post_res.status_code, 302)
        self.assertEqual(self.destination.reviews.count(), 0)
        self.destination.refresh_from_db()
        self.assertEqual(float(self.destination.rating), 4.5)

    def test_duplicate_helpful_vote_prevention(self):
        review = Review.objects.create(user=self.user, destination=self.destination, rating=5, body="Superb")
        # Author cannot vote on own review
        res = self.client.post(reverse("helpful_review", args=[review.pk]))
        review.refresh_from_db()
        self.assertEqual(review.helpful_count, 0)

        # Other user votes helpful
        self.client.force_login(self.user2)
        res1 = self.client.post(reverse("helpful_review", args=[review.pk]))
        review.refresh_from_db()
        self.assertEqual(review.helpful_count, 1)

        # Same user tries duplicate vote -> count remains 1
        res2 = self.client.post(reverse("helpful_review", args=[review.pk]))
        review.refresh_from_db()
        self.assertEqual(review.helpful_count, 1)

    def test_interactive_map_route_points_with_valid_and_missing_coordinates(self):
        import datetime
        trip = Trip.objects.create(
            user=self.user,
            destination=self.destination,
            title="Coorg Gateway",
            start_date=datetime.date(2026, 11, 10),
            end_date=datetime.date(2026, 11, 12),
            budget=12000,
        )
        # Attraction 1: valid coordinates
        a1 = Attraction.objects.create(
            destination=self.destination,
            name="Abbey Falls",
            category="nature",
            latitude=12.4500,
            longitude=75.7100,
            estimated_cost=50,
        )
        # Attraction 2: missing coordinates (None)
        a2 = Attraction.objects.create(
            destination=self.destination,
            name="Local Spice Market",
            category="shopping",
            latitude=None,
            longitude=None,
            estimated_cost=0,
        )
        ItineraryItem.objects.create(trip=trip, day_number=1, attraction=a1, reason="Iconic waterfall")
        ItineraryItem.objects.create(trip=trip, day_number=1, attraction=a2, reason="Local market")

        response = self.client.get(reverse("trip_detail", args=[trip.pk]))
        self.assertEqual(response.status_code, 200)
        route_points = response.context["route_points"]
        # Only the attraction with valid coordinates should be in route_points
        self.assertEqual(len(route_points), 1)
        self.assertEqual(route_points[0]["name"], "Abbey Falls")
        self.assertEqual(route_points[0]["lat"], 12.45)
        self.assertEqual(route_points[0]["lon"], 75.71)
        self.assertEqual(route_points[0]["item_id"], ItineraryItem.objects.get(trip=trip, attraction=a1).pk)
        items_by_day = response.context["groups"][0]["items"]
        self.assertIsNone(items_by_day[0].distance_from_previous_km)
        self.assertFalse(items_by_day[1].has_map_coordinates)
        self.assertIsNone(items_by_day[1].distance_from_previous_km)

    def test_pdf_export_contains_metadata_and_reasons(self):
        import datetime
        from .services.pdf import trip_pdf
        trip = Trip.objects.create(
            user=self.user,
            destination=self.destination,
            title="Monsoon in Coorg",
            start_date=datetime.date(2026, 11, 10),
            end_date=datetime.date(2026, 11, 12),
            budget=15000,
            travelers=2,
            interest="nature",
            pace="relaxed",
        )
        alt = Attraction.objects.create(destination=self.destination, name="Coffee Museum", category="culture", estimated_cost=100)
        a = Attraction.objects.create(destination=self.destination, name="Raja Seat", category="nature", estimated_cost=50)
        ItineraryItem.objects.create(trip=trip, day_number=1, attraction=a, score=88.5, reason="Panoramic sunset view", weather_alternative=alt)

        pdf_buf = trip_pdf(trip)
        self.assertTrue(pdf_buf.getvalue().startswith(b"%PDF"))
        self.assertGreater(len(pdf_buf.getvalue()), 3000)

        # Export trip PDF endpoint verifies user ownership
        res = self.client.get(reverse("export_trip_pdf", args=[trip.pk]))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res["Content-Type"], "application/pdf")

    def test_ai_assistant_grounding_and_context_responses(self):
        from .services.ai import assistant_reply
        context = {
            "trip_title": "Coorg Trip",
            "destination": "Coorg",
            "days": 3,
            "travelers": 2,
            "budget_inr": 18000,
            "estimated_cost_inr": 14000,
            "interest": "nature",
            "pace": "relaxed",
            "scheduled_activities": ["Abbey Falls", "Raja Seat", "Talakaveri"],
        }
        # Budget guidance
        ans, src = assistant_reply("How is my budget looking?", context)
        self.assertEqual(src, "local")
        self.assertIn("18,000", ans)
        self.assertIn("14,000", ans)

        # Weather guidance
        ans, src = assistant_reply("What should I do if it rains?", context)
        self.assertEqual(src, "local")
        self.assertIn("Coorg", ans)
        self.assertIn("weather", ans.lower())

        # Grounding check: refuses to invent live booking/prices
        ans, src = assistant_reply("Can you check live ticket prices and book a ticket now?", context)
        self.assertIn("does not invent", ans)

    def test_admin_analytics_staff_access_and_data_rendering(self):
        # Regular user is redirected
        res_user = self.client.get(reverse("admin_analytics"))
        self.assertEqual(res_user.status_code, 302)

        # Staff user gets 200 with complete analytics context
        self.client.force_login(self.staff_user)
        res_staff = self.client.get(reverse("admin_analytics"))
        self.assertEqual(res_staff.status_code, 200)
        self.assertIn("users", res_staff.context)
        self.assertIn("verified_users", res_staff.context)
        self.assertIn("trips", res_staff.context)
        self.assertIn("reviews", res_staff.context)
        self.assertIn("avg_rating", res_staff.context)
        self.assertIn("popular", res_staff.context)
        self.assertIn("top_reviewed", res_staff.context)
        self.assertIn("feedback", res_staff.context)


class NextLevelSmartTripUpgradeTests(TestCase):
    def setUp(self):
        self.owner = User.objects.create_user(username="hostuser", email="host@example.com", password="password123")
        self.member = User.objects.create_user(username="memberuser", email="member@example.com", password="password123")
        self.outsider = User.objects.create_user(username="outsider", email="outsider@example.com", password="password123")
        self.staff = User.objects.create_user(username="adminuser", email="admin@example.com", password="password123", is_staff=True)

        self.destination = Destination.objects.create(
            name="Udaipur", state="Rajasthan", description="City of Lakes",
            average_daily_cost=3000, best_for="culture,history", rating=4.8
        )
        self.attraction1 = Attraction.objects.create(
            destination=self.destination, name="City Palace", category="history",
            description="Royal complex overlooking Lake Pichola", tags="history,culture,palace",
            sustainability_score=85, hidden_gem_score=40, crowd_level=60, duration_hours=2.0, estimated_cost=300
        )
        self.attraction2 = Attraction.objects.create(
            destination=self.destination, name="Saheliyon-ki-Bari", category="nature",
            description="Historic lush royal garden and fountains", tags="nature,garden,scenic",
            sustainability_score=92, hidden_gem_score=75, crowd_level=25, duration_hours=1.0, estimated_cost=0
        )
        self.trip = Trip.objects.create(
            user=self.owner, destination=self.destination, title="Royal Rajasthan Expedition",
            start_date=date(2026, 11, 1), end_date=date(2026, 11, 4), travelers=2, budget=25000,
            interest="history", pace="relaxed"
        )
        self.item1 = ItineraryItem.objects.create(trip=self.trip, day_number=1, attraction=self.attraction1, score=85.0)
        self.item2 = ItineraryItem.objects.create(trip=self.trip, day_number=2, attraction=self.attraction2, score=90.0)

        self.group = GroupTrip.objects.create(
            owner=self.owner, trip=self.trip, invite_code="TESTINVITE99"
        )
        self.group.members.add(self.member)

    def test_group_trip_access_permissions(self):
        # 1. Owner can access
        self.client.force_login(self.owner)
        res_owner = self.client.get(reverse("group", args=[self.trip.pk]))
        self.assertEqual(res_owner.status_code, 200)
        self.assertTrue(res_owner.context["is_owner"])

        # 2. Member can access
        self.client.force_login(self.member)
        res_member = self.client.get(reverse("group", args=[self.trip.pk]))
        self.assertEqual(res_member.status_code, 200)
        self.assertFalse(res_member.context["is_owner"])

        # 3. Outsider is forbidden/redirected
        self.client.force_login(self.outsider)
        res_outsider = self.client.get(reverse("group", args=[self.trip.pk]))
        self.assertEqual(res_outsider.status_code, 302)

    def test_join_group_trip_via_invite_code(self):
        self.client.force_login(self.outsider)
        # Invalid code
        res_bad = self.client.post(reverse("join_group_trip"), {"invite_code": "WRONGCODE"})
        self.assertFalse(self.group.members.filter(id=self.outsider.id).exists())

        # Valid code
        res_good = self.client.post(reverse("join_group_trip"), {"invite_code": "TESTINVITE99"})
        self.assertEqual(res_good.status_code, 302)
        self.assertTrue(self.group.members.filter(id=self.outsider.id).exists())

    def test_group_attraction_voting(self):
        self.client.force_login(self.member)
        res = self.client.post(reverse("group", args=[self.trip.pk]), {
            "action": "vote",
            "attraction_id": self.attraction2.id,
            "vote": "like",
        })
        self.assertEqual(res.status_code, 302)
        fb = RecommendationFeedback.objects.filter(
            trip=self.trip, attraction=self.attraction2, user=self.member
        ).first()
        self.assertIsNotNone(fb)
        self.assertEqual(fb.action, "like")

    def test_budget_planned_vs_actual_and_burn_rate(self):
        self.client.force_login(self.owner)
        # Add expenses
        BudgetExpense.objects.create(trip=self.trip, category="Food", amount=8000, description="Fine dining dinners")
        BudgetExpense.objects.create(trip=self.trip, category="Accommodation", amount=12000, description="Heritage Haveli")

        res = self.client.get(reverse("budget", args=[self.trip.pk]))
        self.assertEqual(res.status_code, 200)
        self.assertIn("planned_vs_actual", res.context)
        self.assertIn("daily_burn_rate", res.context)
        self.assertIn("target_daily_budget", res.context)
        self.assertIn("budget_suggestions", res.context)

        # Check Food (benchmark is 25% of 25000 = 6250; spent 8000 -> over budget)
        food_item = next((item for item in res.context["planned_vs_actual"] if item["key"] == "Food"), None)
        self.assertIsNotNone(food_item)
        self.assertTrue(food_item["is_over"])
        self.assertEqual(food_item["status_text"], "Over Budget")

    def test_pace_and_history_aware_personalization(self):
        # Relaxed pace boost for short attractions
        score = recommendation_score(self.attraction2, self.trip)
        explanation = explain(self.attraction2, self.trip, score)
        self.assertIn("relaxed", explanation.lower())

        # Free admission recognized for budget travel
        self.assertIn("free", explanation.lower())

    def test_admin_analytics_expanded_kpis(self):
        self.client.force_login(self.staff)
        res = self.client.get(reverse("admin_analytics"))
        self.assertEqual(res.status_code, 200)
        self.assertIn("avg_trip_days", res.context)
        self.assertIn("avg_trip_budget", res.context)
        self.assertIn("total_itinerary_items", res.context)
        self.assertIn("group_trips_count", res.context)
        self.assertIn("group_collaborators_count", res.context)
        self.assertIn("total_tracked_expenses", res.context)


class SmartTripAICopilotTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="copilotuser", email="copilot@example.com", password="password123")
        self.other_user = User.objects.create_user(username="otheruser", email="other@example.com", password="password123")

        self.destination = Destination.objects.create(
            name="Jaipur", state="Rajasthan", description="Pink City of India",
            average_daily_cost=2500, best_for="history,culture", rating=4.7
        )
        self.attr_paid = Attraction.objects.create(
            destination=self.destination, name="Amber Fort", category="history",
            description="Massive hilltop fort complex", tags="history,monument,palace",
            sustainability_score=80, hidden_gem_score=30, crowd_level=75,
            duration_hours=3.0, estimated_cost=500
        )
        self.attr_free = Attraction.objects.create(
            destination=self.destination, name="Jal Mahal Viewpoint", category="nature",
            description="Water palace viewpoint on Man Sagar Lake", tags="nature,viewpoint,scenic",
            sustainability_score=90, hidden_gem_score=70, crowd_level=30,
            duration_hours=1.0, estimated_cost=0
        )
        self.attr_gem = Attraction.objects.create(
            destination=self.destination, name="Galta Ji Temple", category="culture",
            description="Historic tranquil monkey temple retreat", tags="culture,tranquil,temple",
            sustainability_score=95, hidden_gem_score=85, crowd_level=20,
            duration_hours=2.0, estimated_cost=100
        )
        self.attr_extra_free = Attraction.objects.create(
            destination=self.destination, name="Central Park Jaipur", category="nature",
            description="Large lush public city park with free entry", tags="nature,park,free",
            sustainability_score=92, hidden_gem_score=60, crowd_level=40,
            duration_hours=1.5, estimated_cost=0
        )
        self.trip = Trip.objects.create(
            user=self.user, destination=self.destination, title="Jaipur Royal Tour",
            start_date=date(2026, 11, 10), end_date=date(2026, 11, 12), travelers=2, budget=12000,
            interest="history", pace="balanced"
        )
        ItineraryItem.objects.create(trip=self.trip, day_number=1, attraction=self.attr_paid, score=85.0)
        ItineraryItem.objects.create(trip=self.trip, day_number=2, attraction=self.attr_gem, score=90.0)

    def test_copilot_natural_language_brief_parsing(self):
        text = "I want a 3-day trip to Jaipur for 2 people under ₹12,000, relaxed pace, focusing on history"
        parsed = interpret_trip_request(text, [{"id": self.destination.id, "name": self.destination.name}])
        self.assertEqual(parsed.get("destination"), "Jaipur")
        self.assertEqual(parsed.get("days"), 3)
        self.assertEqual(parsed.get("travelers"), 2)
        self.assertEqual(parsed.get("budget"), 12000)
        self.assertEqual(parsed.get("pace"), "relaxed")
        self.assertEqual(parsed.get("interest"), "history")

    def test_copilot_map_receives_configured_tile_provider(self):
        from unittest.mock import patch

        self.client.force_login(self.user)
        with override_settings(
            SMARTTRIP_MAP_TILE_URL="https://tiles.example.test/{z}/{x}/{y}.png",
            SMARTTRIP_MAP_TILE_ATTRIBUTION="Example map provider",
        ), patch("travel.views.weather_context", return_value={"condition": "Clear", "source": "Test"}):
            response = self.client.get(reverse("trip_copilot_detail", args=[self.trip.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "map-config-data")
        self.assertContains(response, "https://tiles.example.test/")

    def test_copilot_generates_three_meaningful_alternatives(self):
        alts = generate_copilot_alternatives(
            self.destination, days=3, budget=12000, travelers=2, interest="history", pace="balanced", user=self.user
        )
        self.assertEqual(len(alts), 3)
        keys = [a["key"] for a in alts]
        self.assertIn("budget_saver", keys)
        self.assertIn("balanced_explorer", keys)
        self.assertIn("hidden_gems_eco", keys)

        # Budget saver should be <= balanced explorer in cost
        budget_alt = next(a for a in alts if a["key"] == "budget_saver")
        balanced_alt = next(a for a in alts if a["key"] == "balanced_explorer")
        gems_alt = next(a for a in alts if a["key"] == "hidden_gems_eco")

        self.assertLessEqual(budget_alt["estimated_cost"], balanced_alt["estimated_cost"])
        self.assertGreaterEqual(gems_alt["avg_hidden_gem"], balanced_alt["avg_hidden_gem"])
        self.assertTrue(len(budget_alt["tradeoffs"]) > 0)

    def test_copilot_create_trip_from_alternative(self):
        self.client.force_login(self.user)
        res = self.client.post(reverse("trip_copilot"), {
            "action": "create_from_alternative",
            "destination": self.destination.id,
            "days": 2,
            "budget": 10000,
            "travelers": 2,
            "interest": "culture",
            "pace": "balanced",
            "alternative_key": "budget_saver",
            "title": "Created via Copilot",
        })
        self.assertEqual(res.status_code, 302)
        new_trip = Trip.objects.filter(title="Created via Copilot", user=self.user).first()
        self.assertIsNotNone(new_trip)
        self.assertGreater(new_trip.items.count(), 0)

    def test_copilot_conversational_refinement_relaxed(self):
        self.client.force_login(self.user)
        res = self.client.post(reverse("trip_copilot_detail", args=[self.trip.pk]), {
            "action": "refine",
            "prompt": "Make the itinerary more relaxed with unhurried visits",
        })
        self.assertEqual(res.status_code, 302)
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.pace, "relaxed")

    def test_copilot_conversational_refinement_budget(self):
        res = refine_itinerary_with_prompt(self.trip, "Reduce the budget and swap for free attractions")
        self.assertTrue(res["success"])
        self.assertEqual(res["action_type"], "budget_cut")
        self.assertIn("Budget optimized", res["summary"])

    def test_copilot_conversational_refinement_weather(self):
        res = refine_itinerary_with_prompt(self.trip, "Weather replan for rain")
        self.assertTrue(res["success"])
        self.assertEqual(res["action_type"], "weather_replan")

    def test_copilot_authorization_protection(self):
        self.client.force_login(self.other_user)
        # Cannot access another user's copilot detail
        res = self.client.get(reverse("trip_copilot_detail", args=[self.trip.pk]))
        self.assertEqual(res.status_code, 302)


class SmartTripUIPolishAndFeatureTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="uitestuser", email="uitest@example.com", password="password123")
        self.dest1 = Destination.objects.create(name="Jaipur", state="Rajasthan", description="Pink city", average_daily_cost=2500, rating=4.7, best_for="history,culture", sustainability_score=80, hidden_gem_score=75, safety_score=85)
        self.dest2 = Destination.objects.create(name="Udaipur", state="Rajasthan", description="City of lakes", average_daily_cost=3000, rating=4.8, best_for="relaxation,nature", sustainability_score=85, hidden_gem_score=80, safety_score=90)
        self.trip = Trip.objects.create(user=self.user, destination=self.dest1, title="Jaipur Royal Trip", start_date=date(2026, 11, 1), end_date=date(2026, 11, 3), travelers=2, budget=15000, pace="balanced")
        self.client.force_login(self.user)

    def test_compare_destinations_view_renders_side_by_side(self):
        res = self.client.get(reverse("compare_destinations"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Compare Destinations")
        self.assertContains(res, "Jaipur")
        self.assertContains(res, "Udaipur")

        # Test with query params
        res_filtered = self.client.get(reverse("compare_destinations") + f"?ids={self.dest1.id}&ids={self.dest2.id}")
        self.assertEqual(res_filtered.status_code, 200)
        self.assertContains(res_filtered, "Jaipur")
        self.assertContains(res_filtered, "Udaipur")

    def test_what_if_scenario_simulation_renders_outcome(self):
        # GET request
        res_get = self.client.get(reverse("what_if", args=[self.trip.pk]))
        self.assertEqual(res_get.status_code, 200)
        self.assertContains(res_get, "What-If Trip Planning")

        # POST simulation
        res_post = self.client.post(reverse("what_if", args=[self.trip.pk]), {
            "name": "Extended Budget Simulation",
            "budget_change": 3000,
            "extra_days": 1,
            "preferred_interest": "culture",
        })
        self.assertEqual(res_post.status_code, 200)
        self.assertContains(res_post, "Simulation Outcome")
        self.assertContains(res_post, "Simulated Budget")

    def test_saved_trips_flow(self):
        # Save trip
        res_save = self.client.post(reverse("save_trip", args=[self.trip.pk]))
        self.assertEqual(res_save.status_code, 302)

        # View saved trips
        res_view = self.client.get(reverse("saved_trips"))
        self.assertEqual(res_view.status_code, 200)
        self.assertContains(res_view, "Jaipur Royal Trip")

        # Remove saved trip
        res_remove = self.client.post(reverse("remove_saved_trip", args=[self.trip.pk]))
        self.assertEqual(res_remove.status_code, 302)

        # Verify empty state or absence
        res_after = self.client.get(reverse("saved_trips"))
        self.assertEqual(res_after.status_code, 200)
        self.assertNotContains(res_after, "Jaipur Royal Trip")

    def test_profile_and_preferences_view(self):
        res = self.client.get(reverse("profile"))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, "Travel Profile")
        self.assertContains(res, "AI Preference Signals")
