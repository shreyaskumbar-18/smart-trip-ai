from datetime import date, timedelta
from unittest.mock import patch
from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from .models import Destination, Attraction, Trip, Review, UserPreference, GroupTrip, BudgetExpense, RecommendationFeedback, Profile, SavedTrip, OTPVerification
from .services.recommendation import recommendation_score, recommendation_score_breakdown, explain
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
        original_budget = trip.budget
        original_interest = trip.interest
        result = what_if(
            trip,
            budget_change=5000,
            extra_days=1,
            preferred_interest="history",
            pace="relaxed",
        )
        self.assertEqual(result["budget"],15000)
        self.assertEqual(result["days"],3)
        self.assertEqual(result["estimated"],12000)
        self.assertTrue(result["has_itinerary"])
        self.assertTrue(result["feasible"])
        self.assertEqual(result["interest"], "history")
        self.assertEqual(result["pace"], "relaxed")
        daily_counts = [
            sum(stop["day"] == day for stop in result["itinerary"])
            for day in range(1, result["days"] + 1)
        ]
        self.assertLessEqual(max(daily_counts, default=0), 2)
        preview_ids = [item["attraction"].id for item in result["itinerary"]]
        self.assertEqual(len(preview_ids), len(set(preview_ids)))
        for item in result["itinerary"]:
            self.assertGreaterEqual(item["day"], 1)
            self.assertLessEqual(item["day"], result["days"])
            self.assertLess(item["start"], item["end"])
        trip.refresh_from_db()
        self.assertEqual(trip.budget, original_budget)
        self.assertEqual(trip.interest, original_interest)
        self.assertEqual(trip.pace, "balanced")

        infeasible = what_if(trip, budget_change=-20000, extra_days=-5)
        self.assertEqual(infeasible["budget"], 0)
        self.assertEqual(infeasible["days"], 1)
        self.assertEqual(infeasible["estimated"], 4000)
        self.assertFalse(infeasible["feasible"])

        no_preference_override = what_if(trip, preferred_interest="", pace="")
        self.assertEqual(no_preference_override["interest"], trip.interest)
        self.assertEqual(no_preference_override["pace"], trip.pace)

    def test_what_if_reports_no_itinerary_when_destination_has_no_attractions(self):
        destination = Destination.objects.create(
            name="Empty Destination", state="Test", description="No attraction data",
            average_daily_cost=1000,
        )
        trip = Trip.objects.create(
            user=self.user, destination=destination, title="No attractions",
            start_date=date(2026, 10, 2), end_date=date(2026, 10, 2),
            travelers=1, budget=5000,
        )

        result = what_if(trip)

        self.assertFalse(result["has_itinerary"])
        self.assertFalse(result["feasible"])
        self.assertIn("No itinerary could be generated", result["feasibility_message"])

    def test_what_if_interest_changes_recommended_stops_without_mutating_trip(self):
        history_stops = [
            Attraction.objects.create(
                destination=self.destination,
                name=f"History Stop {index}",
                category="history",
                description="A history attraction",
                sustainability_score=100,
                hidden_gem_score=100,
                crowd_level=0,
            )
            for index in range(2)
        ]
        trip = Trip.objects.create(
            user=self.user,
            destination=self.destination,
            title="Interest preview",
            start_date=date(2026, 10, 2),
            end_date=date(2026, 10, 2),
            travelers=1,
            budget=10000,
            interest="nature",
            pace="relaxed",
        )

        history_preview = what_if(trip, preferred_interest="history")
        nature_preview = what_if(trip, preferred_interest="nature")

        self.assertEqual(
            {stop["attraction"].id for stop in history_preview["itinerary"]},
            {attraction.id for attraction in history_stops},
        )
        self.assertIn(
            self.attraction.id,
            {stop["attraction"].id for stop in nature_preview["itinerary"]},
        )
        trip.refresh_from_db()
        self.assertEqual(trip.interest, "nature")
        self.assertEqual(trip.pace, "relaxed")
        self.assertEqual(trip.items.count(), 0)

    def test_optimizer_deduplicates_waterfall_aliases_but_keeps_nearby_stops(self):
        from .services.optimizer import optimize_trip

        trip = Trip.objects.create(
            user=self.user,
            destination=self.destination,
            title="Duplicate attraction preview",
            start_date=date(2026, 10, 2),
            end_date=date(2026, 10, 2),
            travelers=1,
            budget=10000,
            pace="packed",
        )
        falls = Attraction.objects.create(
            destination=self.destination,
            name="Jogini Falls",
            category="nature",
            description="Waterfall trail",
            estimated_cost=100,
            latitude=32.2825,
            longitude=77.214,
        )
        waterfall = Attraction.objects.create(
            destination=self.destination,
            name="Jogini Waterfall",
            category="Nature",
            description="Waterfall reached by a nature walk",
            estimated_cost=0,
        )
        nearby = Attraction.objects.create(
            destination=self.destination,
            name="Vashisht Temple",
            category="culture",
            description="A distinct nearby temple",
            latitude=32.2826,
            longitude=77.2141,
        )

        plan = optimize_trip(trip, [falls, waterfall, nearby])
        selected_ids = [item["attraction"].id for item in plan]

        self.assertIn(falls.id, selected_ids)
        self.assertNotIn(waterfall.id, selected_ids)
        self.assertIn(nearby.id, selected_ids)
        self.assertEqual(len(selected_ids), len(set(selected_ids)))

    def test_what_if_uses_lower_ticket_cost_alternatives_and_keeps_overall_feasibility_rule(self):
        from unittest.mock import patch

        destination = Destination.objects.create(
            name="Budget Preview City",
            state="Test",
            description="Budget optimization fixture",
            average_daily_cost=2000,
        )
        trip = Trip.objects.create(
            user=self.user,
            destination=destination,
            title="Ticket budget preview",
            start_date=date(2026, 10, 2),
            end_date=date(2026, 10, 2),
            travelers=1,
            budget=2000,
            pace="packed",
        )
        attractions = [
            Attraction.objects.create(
                destination=destination,
                name=name,
                category=category,
                description=name,
                estimated_cost=cost,
            )
            for name, category, cost in (
                ("Top Costly Stop", "history", 1900),
                ("Second Costly Stop", "culture", 1900),
                ("Affordable Stop A", "food", 1000),
                ("Affordable Stop B", "nature", 1000),
            )
        ]
        scores = {
            attractions[0].id: 100,
            attractions[1].id: 90,
            attractions[2].id: 80,
            attractions[3].id: 75,
        }
        saved_item = ItineraryItem.objects.create(
            trip=trip, day_number=1, attraction=attractions[0], start_time="09:00"
        )

        with patch(
            "travel.services.optimizer.recommendation_score",
            side_effect=lambda attraction, _trip, _feedback=None: scores[attraction.id],
        ), patch(
            "travel.services.recommendation.recommendation_score",
            side_effect=lambda attraction, _trip, _feedback=None: scores[attraction.id],
        ):
            feasible_preview = what_if(trip)
            infeasible_preview = what_if(trip, budget_change=-500)

        feasible_ids = {item["attraction"].id for item in feasible_preview["itinerary"]}
        self.assertTrue(feasible_preview["budget_optimized"])
        self.assertEqual(feasible_ids, {attractions[2].id, attractions[3].id})
        self.assertEqual(feasible_preview["ticket_estimated"], 2000)
        self.assertTrue(feasible_preview["feasible"])

        self.assertTrue(infeasible_preview["budget_optimized"])
        self.assertLessEqual(infeasible_preview["ticket_estimated"], infeasible_preview["budget"])
        self.assertFalse(infeasible_preview["feasible"])
        self.assertIn("exceeds the simulated budget by ₹500", infeasible_preview["feasibility_message"])
        trip.refresh_from_db()
        self.assertEqual(list(trip.items.values_list("pk", flat=True)), [saved_item.pk])

    def test_what_if_preview_explanations_are_concise_and_use_stored_signals(self):
        trip = Trip.objects.create(
            user=self.user,
            destination=self.destination,
            title="Explanation preview",
            start_date=date(2026, 10, 2),
            end_date=date(2026, 10, 2),
            travelers=1,
            budget=10000,
            interest="nature",
            pace="balanced",
            sustainability_priority=3,
            include_hidden_gems=True,
        )
        self.attraction.sustainability_score = 95
        self.attraction.hidden_gem_score = 90
        self.attraction.crowd_level = 20
        self.attraction.save(update_fields=["sustainability_score", "hidden_gem_score", "crowd_level"])

        result = what_if(trip)
        explanation = result["itinerary"][0]["reason"]

        self.assertIn("matches your nature interest", explanation)
        self.assertIn("sustainability 95/100", explanation)
        self.assertIn("hidden-gem score 90/100", explanation)
        self.assertEqual(explanation.count("sustainability"), 1)
        self.assertEqual(explanation.count("Recommendation score:"), 1)
        self.assertLessEqual(explanation.count(";"), 4)

    def test_feedback_updates_preference(self):
        before = get_preferences(self.user).nature
        update_preference_from_feedback(self.user, self.attraction, "like")
        after = get_preferences(self.user).nature
        self.assertGreater(after, before)

    def test_score_breakdown_preserves_existing_score_and_ranking(self):
        from types import SimpleNamespace

        trip = Trip.objects.create(
            user=self.user,
            destination=self.destination,
            title="Score audit",
            start_date=date(2026, 10, 2),
            end_date=date(2026, 10, 3),
            travelers=2,
            budget=20000,
            interest="culture",
            pace="relaxed",
            sustainability_priority=3,
            include_hidden_gems=True,
        )
        scored_attraction = Attraction.objects.create(
            destination=self.destination,
            name="Scenic Nature Park",
            category="nature",
            description="A scenic park",
            estimated_cost=4000,
            duration_hours=4,
            crowd_level=30,
            sustainability_score=80,
            hidden_gem_score=70,
            tags="nature",
        )
        culture_attraction = Attraction.objects.create(
            destination=self.destination,
            name="Culture Hall",
            category="culture",
            description="Culture hall",
            estimated_cost=0,
            duration_hours=2,
            crowd_level=100,
            sustainability_score=0,
            hidden_gem_score=0,
            tags="culture",
        )
        preferences = SimpleNamespace(
            nature=0.6, culture=0.2, adventure=0.5, food=0.5, history=0.5,
            shopping=0.5, relaxation=0.5, hidden_gems=0.7, sustainability=0.8,
        )
        with patch("travel.services.recommendation.get_preferences", return_value=preferences), patch(
            "travel.services.recommendation.preference_summary", return_value=["park"]
        ):
            scored_attraction_id = scored_attraction.pk
            trip._disliked_attraction_ids = {scored_attraction_id}
            original_score = recommendation_score(scored_attraction, trip, {scored_attraction_id})
            breakdown = recommendation_score_breakdown(scored_attraction, trip, {scored_attraction_id})
            ordered = sorted(
                [culture_attraction, scored_attraction],
                key=lambda attraction: recommendation_score(attraction, trip, {scored_attraction_id}),
                reverse=True,
            )

        self.assertEqual(original_score, 63.92)
        self.assertEqual(breakdown["score"], original_score)
        self.assertAlmostEqual(breakdown["raw_score"], 63.92)
        self.assertFalse(breakdown["clamped"])
        self.assertAlmostEqual(sum(item["value"] for item in breakdown["components"]), breakdown["raw_score"])
        component_values = {item["label"]: item["value"] for item in breakdown["components"]}
        self.assertAlmostEqual(component_values["Learned category preference"], 10.8)
        self.assertEqual(component_values["Profile or feedback-derived interest match"], 10)
        self.assertEqual(component_values["Sustainability score weighted by trip priority"], 24)
        self.assertAlmostEqual(component_values["Hidden-gem score weighted by learned preference"], 3.92)
        self.assertEqual(component_values["Positive attraction feedback"], 12)
        self.assertEqual(component_values["Negative attraction feedback"], -18)
        self.assertEqual([item.pk for item in ordered], [scored_attraction.pk, culture_attraction.pk])

    def test_cubbon_like_breakdown_reconciles_and_score_saturates(self):
        from types import SimpleNamespace

        trip = Trip.objects.create(
            user=self.user,
            destination=self.destination,
            title="Cubbon score reconciliation",
            start_date=date(2026, 10, 2),
            end_date=date(2026, 10, 2),
            travelers=1,
            budget=0,
            interest="nature",
            pace="relaxed",
            sustainability_priority=4,
            include_hidden_gems=True,
        )
        Trip.objects.create(
            user=self.user,
            destination=self.destination,
            title="Prior nature trip",
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 1),
            interest="nature",
        )
        attraction = Attraction.objects.create(
            destination=self.destination,
            name="Cubbon Park",
            category="nature",
            description="A scenic garden park",
            estimated_cost=0,
            duration_hours=2,
            crowd_level=25,
            sustainability_score=88,
            hidden_gem_score=55,
        )
        learned_preference = 0.5909090909090909
        preferences = SimpleNamespace(
            nature=0.5, culture=0.5, adventure=0.5, food=0.5, history=0.5,
            shopping=0.5, relaxation=0.5, hidden_gems=learned_preference,
            sustainability=learned_preference,
        )

        with patch("travel.services.recommendation.get_preferences", return_value=preferences), patch(
            "travel.services.recommendation.preference_summary", return_value=["park"]
        ):
            breakdown = recommendation_score_breakdown(attraction, trip)
            direct_score = recommendation_score(attraction, trip)

        component_values = {item["label"]: item["value"] for item in breakdown["components"]}
        self.assertAlmostEqual(breakdown["raw_score"], 132.9)
        self.assertAlmostEqual(sum(item["value"] for item in breakdown["components"]), breakdown["raw_score"])
        self.assertAlmostEqual(component_values["Interest match baseline"], 35)
        self.assertAlmostEqual(component_values["Learned category preference"], 9)
        self.assertAlmostEqual(component_values["Profile or feedback-derived interest match"], 10)
        self.assertAlmostEqual(component_values["Sustainability score weighted by trip priority"], 35.2)
        self.assertAlmostEqual(component_values["Hidden-gem score enabled for this trip"], 11)
        self.assertAlmostEqual(component_values["Hidden-gem score weighted by learned preference"], 2.6)
        self.assertAlmostEqual(component_values["Sustainability score weighted by learned preference"], 2.6)
        self.assertAlmostEqual(component_values["Lower-crowd factor"], 7.5)
        self.assertAlmostEqual(component_values["Relaxed-pace duration fit"], 8)
        self.assertAlmostEqual(component_values["Relaxed-pace setting fit"], 5)
        self.assertAlmostEqual(component_values["Trip-history match"], 7)
        self.assertTrue(breakdown["clamped"])
        self.assertEqual(breakdown["score"], 100)
        self.assertEqual(direct_score, 100)

    def test_recommendation_breakdown_clamps_scores_at_both_bounds(self):
        from types import SimpleNamespace

        class MinimalTrip:
            interest = "nature"
            pace = ""
            sustainability_priority = 10
            include_hidden_gems = True
            budget = 0
            days = 1
            travelers = 1
            user = None

        high_attraction = SimpleNamespace(
            id=1, category="nature", tags="nature", description="nature park", duration_hours=2,
            sustainability_score=100, hidden_gem_score=100, crowd_level=0, estimated_cost=0,
        )
        low_attraction = SimpleNamespace(
            id=2, category="", tags="", description="", duration_hours=2,
            sustainability_score=0, hidden_gem_score=0, crowd_level=100, estimated_cost=0,
        )

        high = recommendation_score_breakdown(high_attraction, MinimalTrip())
        low_trip = MinimalTrip()
        low_trip.interest = ""
        low_trip._disliked_attraction_ids = {low_attraction.id}
        low = recommendation_score_breakdown(low_attraction, low_trip)

        self.assertGreater(high["raw_score"], 100)
        self.assertEqual(high["score"], 100)
        self.assertTrue(high["clamped"])
        self.assertLess(low["raw_score"], 0)
        self.assertEqual(low["score"], 0)
        self.assertTrue(low["clamped"])

    def test_score_breakdown_handles_missing_optional_user_data(self):
        trip = Trip.objects.create(
            user=self.user,
            destination=self.destination,
            title="Incomplete optional profile",
            start_date=date(2026, 10, 2),
            end_date=date(2026, 10, 2),
            travelers=1,
            budget=5000,
        )
        trip.user = None

        breakdown = recommendation_score_breakdown(self.attraction, trip, feedback_ids=None)

        self.assertGreaterEqual(breakdown["score"], 0)
        self.assertLessEqual(breakdown["score"], 100)
        self.assertTrue(breakdown["components"])
        self.assertFalse(any("learned category" in item["label"].lower() for item in breakdown["components"]))

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

    def test_trip_assistant_route_question_uses_saved_itinerary(self):
        from unittest.mock import patch

        ItineraryItem.objects.create(
            trip=self.trip,
            day_number=1,
            attraction=self.outdoor,
            start_time="09:00",
            score=75,
            reason="Near the coast",
        )
        ItineraryItem.objects.create(
            trip=self.trip,
            day_number=1,
            attraction=self.indoor,
            start_time="13:00",
            score=70,
            reason="Indoor activity",
        )
        self.client.force_login(self.user)

        with (
            patch("travel.services.ai._database_travel_reply") as database_reply,
            patch("travel.services.ai._chat") as chat,
        ):
            response = self.client.post(
                reverse("assistant_trip", args=[self.trip.pk]),
                {"question": "How do I reduce travel time between attractions?"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["question"], "How do I reduce travel time between attractions?")
        self.assertEqual(response.context["answer_source"], "local")
        self.assertContains(response, "Baga Beach → Local Museum")
        self.assertContains(response, "Group nearby attractions")
        self.assertContains(response, "avoid crossing the same area repeatedly")
        self.assertContains(response, "no live routing result")
        self.assertNotContains(response, "Which destination would you like recommendations for?")
        database_reply.assert_not_called()
        chat.assert_not_called()

    def test_route_question_without_trip_context_uses_local_guidance(self):
        answer, source = assistant_reply("How do I reduce travel time between attractions?")

        self.assertEqual(source, "local")
        self.assertIn("Group nearby attractions", answer)
        self.assertIn("geographic cluster", answer)
        self.assertIn("no live routing result", answer)
        self.assertNotIn("Which destination would you like recommendations for?", answer)

    def test_route_fix_preserves_destination_weather_and_budget_intents(self):
        from unittest.mock import patch

        context = {
            "trip_title": self.trip.title,
            "destination": self.destination.name,
            "budget_inr": 15000,
            "estimated_cost_inr": 12000,
            "days": 2,
            "travelers": 1,
        }
        with patch("travel.services.ai._chat", return_value=None):
            recommendation, recommendation_source = assistant_reply(
                "What attractions should I visit in Goa?"
            )
            weather, weather_source = assistant_reply("What should I do if it rains?", context)
            budget, budget_source = assistant_reply("How do I keep my trip within budget?", context)

        self.assertEqual(recommendation_source, "local")
        self.assertIn("Goa", recommendation)
        self.assertIn("Baga Beach", recommendation)
        self.assertNotIn("Group nearby attractions", recommendation)
        self.assertEqual(weather_source, "local")
        self.assertIn("Goa", weather)
        self.assertIn("weather", weather.lower())
        self.assertEqual(budget_source, "local")
        self.assertIn("15,000", budget)
        self.assertIn("12,000", budget)

    def test_assistant_post_renders_the_answer_and_handles_empty_question(self):
        from unittest.mock import patch

        self.client.force_login(self.user)
        page = self.client.get(reverse("assistant"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, '<form method="post">')
        self.assertContains(page, 'name="question"')
        self.assertContains(page, 'type="submit"')
        self.assertContains(page, 'id="aiFab"')
        self.assertContains(page, 'id="aiClose"')
        self.assertContains(page, 'id="aiChatForm"')
        self.assertContains(page, 'data-question="Suggest places to visit in Mysuru"')

        question = "How do I reduce travel time between attractions?"
        with patch("travel.services.ai._chat", return_value=None):
            response = self.client.post(reverse("assistant"), {"question": question})
            empty_response = self.client.post(reverse("assistant"), {"question": "   "})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["question"], question)
        self.assertContains(response, "Group nearby attractions")
        self.assertEqual(empty_response.status_code, 200)
        self.assertContains(empty_response, "Tell me what you need help with")

    def test_assistant_ajax_returns_the_answer_as_json(self):
        from unittest.mock import patch

        self.client.force_login(self.user)
        with patch("travel.views.assistant_reply", return_value=("A direct local answer.", "local")):
            response = self.client.post(
                reverse("assistant"),
                {"question": "Tell me about routes"},
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/json")
        self.assertEqual(response.json(), {"answer": "A direct local answer.", "source": "local"})

    def test_trip_assistant_ajax_keeps_the_authenticated_trip_context(self):
        from unittest.mock import patch

        self.client.force_login(self.user)
        with patch("travel.views.assistant_reply", return_value=("Trip-aware answer.", "local")) as reply:
            response = self.client.post(
                reverse("assistant_trip", args=[self.trip.pk]),
                {"question": "How is this itinerary arranged?"},
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["answer"], "Trip-aware answer.")
        context = reply.call_args.args[1]
        self.assertEqual(context["destination"], self.destination.name)
        self.assertEqual(context["trip_title"], self.trip.title)
        self.assertEqual(context["_user"], self.user)

    def test_group_member_can_use_trip_assistant_but_outsider_cannot(self):
        collaborator = User.objects.create_user(
            username="assistantcollaborator", email="assistantcollaborator@example.com", password="testpass123"
        )
        group = GroupTrip.objects.create(
            owner=self.user,
            trip=self.trip,
            invite_code="assistant-group-test",
        )
        group.members.add(collaborator)
        self.client.force_login(collaborator)

        with patch("travel.views.assistant_reply", return_value=("Group trip answer.", "local")) as reply:
            member_response = self.client.post(
                reverse("assistant_trip", args=[self.trip.pk]),
                {"question": "Help with this trip"},
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )
        self.assertEqual(member_response.status_code, 200)
        self.assertEqual(reply.call_args.args[1]["destination"], self.destination.name)

        outsider = User.objects.create_user(
            username="assistantoutsider", email="assistantoutsider@example.com", password="testpass123"
        )
        self.client.force_login(outsider)
        outsider_response = self.client.post(
            reverse("assistant_trip", args=[self.trip.pk]),
            {"question": "Help with this trip"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(outsider_response.status_code, 404)

    def test_local_destination_discovery_filters_by_requested_state(self):
        from unittest.mock import patch

        Destination.objects.create(
            name="Mysuru", state="Karnataka", description="Heritage city",
            average_daily_cost=1800, best_for="culture,history",
        )
        with patch("travel.services.ai._chat") as chat:
            answer, source = assistant_reply("Suggest destinations in Karnataka")

        self.assertEqual(source, "local")
        self.assertIn("Mysuru", answer)
        self.assertNotIn("Jaipur", answer)
        chat.assert_not_called()

    def test_local_two_day_trip_plan_uses_optimizer_without_saving_a_trip(self):
        from unittest.mock import patch

        hampi = Destination.objects.create(
            name="Hampi", state="Karnataka", description="Heritage landscape",
            average_daily_cost=2500, best_for="history,culture",
        )
        Attraction.objects.create(
            destination=hampi, name="Virupaksha Temple", category="history",
            description="Historic temple", estimated_cost=100, duration_hours=2,
            sustainability_score=80, hidden_gem_score=50, crowd_level=40,
            tags="temple,heritage",
        )
        Attraction.objects.create(
            destination=hampi, name="Hampi Bazaar", category="culture",
            description="Historic market street", estimated_cost=0, duration_hours=1,
            sustainability_score=80, hidden_gem_score=50, crowd_level=30,
            tags="market,heritage",
        )
        original_trip_count = Trip.objects.count()

        with patch("travel.services.ai._chat") as chat:
            answer, source = assistant_reply(
                "Plan a two-day trip to Hampi under ₹5,000",
                {"_user": self.user, "destination": self.destination.name},
            )

        self.assertEqual(source, "local")
        self.assertIn("2-day itinerary preview for Hampi", answer)
        self.assertIn("Virupaksha Temple", answer)
        self.assertIn("Requested budget: ₹5,000", answer)
        self.assertIn("does not guarantee full trip feasibility", answer)
        self.assertIn("does not save or change an itinerary", answer)
        self.assertEqual(Trip.objects.count(), original_trip_count)
        chat.assert_not_called()

    def test_local_trip_plan_asks_for_destination_when_essential_context_is_missing(self):
        from unittest.mock import patch

        with patch("travel.services.ai._chat") as chat:
            answer, source = assistant_reply("Help me plan a trip within ₹5,000")

        self.assertEqual(source, "local")
        self.assertIn("₹5,000", answer)
        self.assertIn("destination and trip length", answer)
        chat.assert_not_called()

    def test_assistant_ajax_empty_message_returns_friendly_json_response(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("assistant"),
            {"question": "   "},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("Tell me what you need help with", response.json()["answer"])

    def test_assistant_ajax_post_still_requires_csrf(self):
        from django.test import Client

        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        page = client.get(reverse("assistant"))
        csrf_token = client.cookies["csrftoken"].value

        rejected = client.post(
            reverse("assistant"),
            {"question": "What should I visit?"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        accepted = client.post(
            reverse("assistant"),
            {"question": "What should I visit?", "csrfmiddlewaretoken": csrf_token},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(page.status_code, 200)
        self.assertEqual(rejected.status_code, 403)
        self.assertEqual(accepted.status_code, 200)
        self.assertIn("answer", accepted.json())

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

    def test_weather_repair_does_not_duplicate_a_later_scheduled_stop(self):
        from unittest.mock import patch

        self.indoor.sustainability_score = 100
        self.indoor.hidden_gem_score = 100
        self.indoor.crowd_level = 0
        self.indoor.save(update_fields=["sustainability_score", "hidden_gem_score", "crowd_level"])
        spare = Attraction.objects.create(
            destination=self.destination,
            name="History Gallery",
            category="history",
            description="Indoor gallery alternative",
            sustainability_score=10,
            hidden_gem_score=10,
            crowd_level=90,
            latitude=15.51,
            longitude=73.81,
        )
        first = ItineraryItem.objects.create(
            trip=self.trip, day_number=1, attraction=self.outdoor, start_time="09:00"
        )
        later = ItineraryItem.objects.create(
            trip=self.trip, day_number=1, attraction=self.indoor, start_time="13:00"
        )
        fake_live_rain = {
            "condition": "Rain",
            "advice": "Indoor activities",
            "source": "Open-Meteo forecast",
            "target_date": "2026-10-20",
        }
        with patch("travel.services.repair.weather_context", return_value=fake_live_rain):
            result = repair_itinerary(
                self.trip, [self.outdoor, self.indoor, spare], trigger="Weather disruption"
            )

        self.assertEqual([item["attraction"].id for item in result], [spare.id, self.indoor.id])
        self.assertEqual(len({item["attraction"].id for item in result}), len(result))
        self.assertEqual(list(self.trip.items.order_by("pk").values_list("pk", flat=True)), [first.pk, later.pk])

    def test_weather_repair_preserves_stop_when_no_alternative_exists(self):
        from unittest.mock import patch

        item = ItineraryItem.objects.create(
            trip=self.trip, day_number=1, attraction=self.outdoor, start_time="09:00"
        )
        fake_live_rain = {
            "condition": "Rain",
            "advice": "Indoor activities",
            "source": "Open-Meteo forecast",
            "target_date": "2026-10-20",
        }
        with patch("travel.services.repair.weather_context", return_value=fake_live_rain):
            result = repair_itinerary(self.trip, [self.outdoor], trigger="Weather disruption")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["attraction"].id, self.outdoor.id)
        self.assertFalse(result[0]["changed"])
        self.assertEqual(self.trip.items.get(pk=item.pk).attraction_id, self.outdoor.id)

    def test_weather_replan_post_applies_only_a_unique_feasible_preview(self):
        from unittest.mock import patch
        from .services.feasibility import check_feasibility

        self.indoor.sustainability_score = 100
        self.indoor.hidden_gem_score = 100
        self.indoor.crowd_level = 0
        self.indoor.save(update_fields=["sustainability_score", "hidden_gem_score", "crowd_level"])
        spare = Attraction.objects.create(
            destination=self.destination,
            name="History Gallery",
            category="history",
            description="Indoor gallery alternative",
            sustainability_score=10,
            hidden_gem_score=10,
            crowd_level=90,
            latitude=15.51,
            longitude=73.81,
        )
        original_first = ItineraryItem.objects.create(
            trip=self.trip, day_number=1, attraction=self.outdoor, start_time="09:00"
        )
        original_second = ItineraryItem.objects.create(
            trip=self.trip, day_number=2, attraction=self.indoor, start_time="09:00"
        )
        original_ids = [original_first.pk, original_second.pk]
        self.client.force_login(self.user)
        fake_live_rain = {
            "condition": "Rain",
            "advice": "Indoor activities",
            "source": "Open-Meteo forecast",
            "target_date": "2026-10-20",
        }
        with patch("travel.views.weather_context", return_value=fake_live_rain), patch(
            "travel.services.repair.weather_context", return_value=fake_live_rain
        ):
            response = self.client.post(reverse("replan", args=[self.trip.pk]), {
                "trigger": "Weather disruption",
            })

        self.assertEqual(response.status_code, 302)
        new_items = list(self.trip.items.order_by("day_number", "pk"))
        self.assertEqual([item.attraction_id for item in new_items], [spare.pk, self.indoor.pk])
        self.assertEqual(len({item.attraction_id for item in new_items}), len(new_items))
        self.assertNotEqual([item.pk for item in new_items], original_ids)
        self.assertTrue(check_feasibility(self.trip)["feasible"])

    def test_offline_demo_weather_never_mutates_itinerary(self):
        from unittest.mock import patch
        ItineraryItem.objects.create(trip=self.trip, day_number=1, attraction=self.outdoor, start_time="09:00")
        fake_demo = {"condition": "Rain", "source": "Offline demo", "advice": "Demo only"}
        with patch("travel.services.repair.weather_context", return_value=fake_demo):
            result = repair_itinerary(self.trip, [self.outdoor, self.indoor], trigger="Weather re-plan")
        self.assertEqual(result[0]["attraction"].id, self.outdoor.id)
        self.assertFalse(result[0]["changed"])

    def test_recommendation_pace_uses_real_duration_hours_field(self):
        from .services.recommendation import recommendation_score
        long_visit = Attraction.objects.create(
            destination=self.destination, name="Long Visit", category="nature",
            description="Nature visit", duration_hours=4.5,
        )
        self.trip.pace = "relaxed"
        relaxed_score = recommendation_score(long_visit, self.trip)
        self.trip.pace = "packed"
        packed_score = recommendation_score(long_visit, self.trip)
        self.assertEqual(packed_score - relaxed_score, 7)


class SmartTripPageRenderTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="pageuser", email="page@example.com", password="testpass123")
        self.destination = Destination.objects.create(name="Mysuru", state="Karnataka", description="Heritage and gardens", average_daily_cost=1800, best_for="history,culture", rating=4.5)
        self.attraction = Attraction.objects.create(destination=self.destination, name="Mysore Palace", category="history", description="Palace visit", estimated_cost=200, duration_hours=2, latitude=12.3052, longitude=76.6552, tags="history,culture")
        self.trip = Trip.objects.create(user=self.user, destination=self.destination, title="Mysuru weekend", start_date=date(2026, 10, 20), end_date=date(2026, 10, 20), travelers=1, budget=5000, interest="history")
        ItineraryItem.objects.create(trip=self.trip, day_number=1, attraction=self.attraction, start_time="09:00", score=80, reason="Matches your interest in history.")
        self.client.force_login(self.user)

    def _create_feedback_test_attraction(self, name, category, destination=None):
        return Attraction.objects.create(
            destination=destination or self.destination,
            name=name,
            category=category,
            description=f"{category} site",
            estimated_cost=10000,
            duration_hours=2,
            crowd_level=100,
            sustainability_score=0,
            hidden_gem_score=0,
            tags="",
        )

    def _standalone_recommendations(self, destination=None):
        destination = destination or self.destination
        response = self.client.get(reverse("recommendations"), {
            "destination": destination.pk,
            "interest": "",
            "pace": "balanced",
        })
        self.assertEqual(response.status_code, 200)
        return response.context["recommendations"]

    def _assert_breakdowns_match_recommendation_scores(self, recommendations):
        for attraction, score, _explanation in recommendations:
            self.assertEqual(attraction.score_breakdown["score"], score)

    def test_destination_cards_use_distinct_local_art_for_missing_images(self):
        names_and_files = (
            ("Chikkamagaluru", "chikkamagaluru.svg"),
            ("Mangaluru", "mangaluru.svg"),
            ("Udupi", "udupi.svg"),
            ("Hampi", "hampi.svg"),
            ("Badami", "badami.svg"),
        )
        for name, _filename in names_and_files:
            Destination.objects.create(
                name=name, state="Karnataka", description=f"{name} destination", best_for="nature"
            )

        response = self.client.get(reverse("destinations"))

        self.assertEqual(response.status_code, 200)
        for name, filename in names_and_files:
            self.assertContains(response, f"travel/images/destination-fallback/{filename}")
            self.assertContains(response, f"travel/images/destinations/{name.casefold()}.jpg")
        self.assertContains(response, "travel/images/mysuru-palace.jpg")
        self.assertNotContains(response, "register-coast.jpg")

    def test_destination_images_keep_saved_url_and_failed_image_has_local_fallback(self):
        destination = Destination.objects.create(
            name="Saved Image Place",
            state="Test",
            description="Destination with a saved image URL",
            best_for="culture",
            image_url="https://images.example.test/saved-place.jpg",
        )

        listing = self.client.get(reverse("destinations"))
        self.assertContains(listing, "https://images.example.test/saved-place.jpg")
        self.assertContains(listing, "travel/images/destination-fallback/destination.svg")

        detail = self.client.get(reverse("destination_detail", args=[destination.pk]))
        self.assertEqual(detail.status_code, 200)
        self.assertContains(detail, "https://images.example.test/saved-place.jpg")

    def test_homepage_links_to_all_destinations_and_renders_all_database_destinations(self):
        names = ["Bengaluru", "Goa", "Manali", "Jaipur", "Munnar"]
        names.extend(["Chikkamagaluru", "Mangaluru", "Udupi", "Hampi", "Badami"])
        for name in names:
            Destination.objects.create(
                name=name,
                state="Karnataka",
                description=f"{name} destination",
                best_for="nature,culture",
                image_url="",
            )

        response = self.client.get(reverse("home"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'href="/destinations/"')
        self.assertContains(response, "Explore All Destinations")
        self.assertEqual(response.context["destination_count"], 11)
        self.assertContains(response, "destinations</span>")
        self.assertEqual(len(response.context["popular"]), 11)
        for name in names:
            self.assertContains(response, name)

    def test_dashboard_uses_consistent_trip_workspace_sections(self):
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "dashboard-heading")
        self.assertContains(response, "dashboard-kpis")
        self.assertContains(response, "Your Trips")

    def test_destinations_listing_covers_all_eleven_rows_and_keeps_new_photo_mapping(self):
        names = ["Bengaluru", "Goa", "Manali", "Jaipur", "Munnar"]
        names.extend(["Chikkamagaluru", "Mangaluru", "Udupi", "Hampi", "Badami"])
        for name in names:
            Destination.objects.create(
                name=name,
                state="Karnataka",
                description=f"{name} destination",
                best_for="nature,culture",
                image_url="",
            )

        response = self.client.get(reverse("destinations"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["destinations"]), 11)
        for name in names:
            self.assertContains(response, name)
        for name in ("chikkamagaluru", "mangaluru", "udupi", "hampi", "badami"):
            self.assertContains(response, f"travel/images/destinations/{name}.jpg")

    def test_recommendations_page_renders_accessible_score_breakdown(self):
        response = self.client.get(reverse("recommendations"), {
            "destination": self.destination.pk,
            "interest": "history",
            "pace": "balanced",
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "View exact score breakdown")
        self.assertContains(response, "Raw score:")
        self.assertContains(response, "Displayed match:")
        self.assertContains(response, "Interest match baseline")
        self.assertContains(response, "Lower-crowd factor")
        attraction, score, explanation = response.context["recommendations"][0]
        self.assertEqual(attraction.score_breakdown["score"], score)
        self.assertTrue(explanation)

    def test_standalone_recommendations_apply_current_users_positive_feedback(self):
        destination = Destination.objects.create(name="Feedback City", state="Test", description="Feedback test")
        culture = self._create_feedback_test_attraction("Culture Site", "culture", destination)
        adventure = self._create_feedback_test_attraction("Adventure Site", "adventure", destination)
        baseline = self._standalone_recommendations(destination)
        baseline_scores = {attraction.pk: score for attraction, score, _ in baseline}

        RecommendationFeedback.objects.create(
            user=self.user, attraction=culture, trip=None, action="like"
        )
        recommendations = self._standalone_recommendations(destination)
        scores = {attraction.pk: score for attraction, score, _ in recommendations}
        culture_result = next(item for item in recommendations if item[0].pk == culture.pk)

        self.assertGreater(scores[culture.pk], baseline_scores[culture.pk])
        self.assertEqual(recommendations[0][0].pk, culture.pk)
        self.assertEqual(culture_result[0].score_breakdown["score"], culture_result[1])
        components = {item["label"]: item["value"] for item in culture_result[0].score_breakdown["components"]}
        self.assertEqual(components["Positive attraction feedback"], 12)
        self.assertIn("you previously liked or saved this attraction", culture_result[2])
        self._assert_breakdowns_match_recommendation_scores(recommendations)
        self.assertIn(adventure.pk, scores)

    def test_standalone_recommendations_apply_current_users_negative_feedback(self):
        destination = Destination.objects.create(name="Feedback City", state="Test", description="Feedback test")
        culture = self._create_feedback_test_attraction("Culture Site", "culture", destination)
        adventure = self._create_feedback_test_attraction("Adventure Site", "adventure", destination)
        baseline = self._standalone_recommendations(destination)
        baseline_scores = {attraction.pk: score for attraction, score, _ in baseline}

        RecommendationFeedback.objects.create(
            user=self.user, attraction=culture, trip=self.trip, action="dislike"
        )
        recommendations = self._standalone_recommendations(destination)
        scores = {attraction.pk: score for attraction, score, _ in recommendations}
        culture_result = next(item for item in recommendations if item[0].pk == culture.pk)

        self.assertLess(scores[culture.pk], baseline_scores[culture.pk])
        self.assertEqual(recommendations[0][0].pk, adventure.pk)
        components = {item["label"]: item["value"] for item in culture_result[0].score_breakdown["components"]}
        self.assertEqual(components["Negative attraction feedback"], -18)
        self.assertIn("recorded feedback discourages this attraction", culture_result[2])
        self._assert_breakdowns_match_recommendation_scores(recommendations)

    def test_another_users_feedback_does_not_change_standalone_scores(self):
        from django.contrib.auth.models import User

        destination = Destination.objects.create(name="Feedback City", state="Test", description="Feedback test")
        culture = self._create_feedback_test_attraction("Culture Site", "culture", destination)
        self._create_feedback_test_attraction("Adventure Site", "adventure", destination)
        baseline = self._standalone_recommendations(destination)
        baseline_scores = {attraction.pk: score for attraction, score, _ in baseline}
        other_user = User.objects.create_user(username="other-feedback-user", password="testpass123")
        RecommendationFeedback.objects.create(
            user=other_user, attraction=culture, trip=self.trip, action="like"
        )

        recommendations = self._standalone_recommendations(destination)
        scores = {attraction.pk: score for attraction, score, _ in recommendations}

        self.assertEqual(scores, baseline_scores)
        self.assertNotIn("Positive attraction feedback", {
            item["label"] for item in next(row for row in recommendations if row[0].pk == culture.pk)[0].score_breakdown["components"]
        })
        self._assert_breakdowns_match_recommendation_scores(recommendations)

    def test_standalone_recommendations_work_without_feedback(self):
        destination = Destination.objects.create(name="Feedback City", state="Test", description="Feedback test")
        self._create_feedback_test_attraction("Culture Site", "culture", destination)

        recommendations = self._standalone_recommendations(destination)

        self.assertTrue(recommendations)
        self._assert_breakdowns_match_recommendation_scores(recommendations)

    def test_duplicate_or_conflicting_feedback_uses_one_latest_direct_signal(self):
        destination = Destination.objects.create(name="Feedback City", state="Test", description="Feedback test")
        culture = self._create_feedback_test_attraction("Culture Site", "culture", destination)
        RecommendationFeedback.objects.create(
            user=self.user, attraction=culture, trip=None, action="like"
        )
        RecommendationFeedback.objects.create(
            user=self.user, attraction=culture, trip=None, action="like"
        )

        repeated_likes = next(
            row for row in self._standalone_recommendations(destination)
            if row[0].pk == culture.pk
        )
        repeated_components = {
            item["label"]: item["value"] for item in repeated_likes[0].score_breakdown["components"]
        }
        self.assertEqual(repeated_components["Positive attraction feedback"], 12)

        RecommendationFeedback.objects.create(
            user=self.user, attraction=culture, trip=None, action="dislike"
        )
        latest_dislike = next(
            row for row in self._standalone_recommendations(destination)
            if row[0].pk == culture.pk
        )
        latest_components = {
            item["label"]: item["value"] for item in latest_dislike[0].score_breakdown["components"]
        }
        self.assertNotIn("Positive attraction feedback", latest_components)
        self.assertEqual(latest_components["Negative attraction feedback"], -18)
        self.assertEqual(latest_dislike[0].score_breakdown["score"], latest_dislike[1])

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
        self.assertContains(response, "Create group invite")
        self.assertFalse(GroupTrip.objects.filter(trip=self.trip).exists())
        response = self.client.post(reverse("group", args=[self.trip.pk]), {"action": "create_group"})
        self.assertEqual(response.status_code, 302)
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

    def test_comparison_quality_components_use_stored_data_and_documented_weights(self):
        from .services.optimizer import itinerary_comparison_breakdown

        self.trip.budget = 1000
        self.trip.travelers = 2
        self.trip.pace = "balanced"
        self.trip.save(update_fields=["budget", "travelers", "pace"])
        first = Attraction.objects.create(
            destination=self.destination, name="First Stop", category="nature",
            description="Nature stop", estimated_cost=100, sustainability_score=80,
            crowd_level=20, latitude=12.0, longitude=76.0,
        )
        second = Attraction.objects.create(
            destination=self.destination, name="Second Stop", category="culture",
            description="Culture stop", estimated_cost=200, sustainability_score=60,
            crowd_level=60, latitude=12.0, longitude=77.0,
        )
        third = Attraction.objects.create(
            destination=self.destination, name="Third Stop", category="adventure",
            description="Adventure stop", estimated_cost=100, sustainability_score=90,
            crowd_level=40,
        )
        scores = {first.pk: 80, second.pk: 60}
        with patch("travel.services.optimizer.recommendation_score", side_effect=lambda attraction, _trip, _ids: scores[attraction.pk]):
            comparison = itinerary_comparison_breakdown(
                self.trip, [first, second], [first, second, third]
            )

        components = {item["key"]: item for item in comparison["components"]}
        self.assertEqual(components["preference_match"]["score"], 70)
        self.assertAlmostEqual(components["coverage"]["score"], 200 / 3)
        self.assertEqual(components["category_variety"]["score"], 100)
        self.assertEqual(components["sustainability"]["score"], 70)
        self.assertEqual(components["crowd_comfort"]["score"], 60)
        self.assertEqual(components["route_compactness"]["score"], 100)
        self.assertAlmostEqual(components["budget_fit"]["score"], 40)
        self.assertEqual(comparison["attraction_cost"], 600)
        self.assertTrue(comparison["budget_feasible"])
        self.assertEqual(comparison["quality_score"], 70.0)
        self.assertAlmostEqual(sum(item["normalized_weight_percent"] for item in components.values()), 100)

    def test_existing_itinerary_quality_formula_remains_unchanged(self):
        from .services.optimizer import itinerary_quality

        destination = Destination.objects.create(
            name="Quality Formula City", state="Test", description="Three stored attractions",
        )
        first = Attraction.objects.create(
            destination=destination, name="Nature Stop", category="nature",
            description="Nature", sustainability_score=80, crowd_level=20,
        )
        second = Attraction.objects.create(
            destination=destination, name="Culture Stop", category="culture",
            description="Culture", sustainability_score=60, crowd_level=60,
        )
        Attraction.objects.create(
            destination=destination, name="Unused Stop", category="adventure",
            description="Adventure", sustainability_score=100, crowd_level=0,
        )
        trip = Trip.objects.create(
            user=self.user, destination=destination, title="Quality formula",
            start_date=date(2026, 10, 20), end_date=date(2026, 10, 20),
            travelers=1, budget=5000, pace="balanced",
        )
        ItineraryItem.objects.create(trip=trip, day_number=1, attraction=first)
        ItineraryItem.objects.create(trip=trip, day_number=1, attraction=second)

        self.assertEqual(itinerary_quality(trip), 72.8)

    def test_comparison_marks_missing_coordinates_unavailable_and_renormalizes(self):
        from .services.optimizer import itinerary_comparison_breakdown

        first = Attraction.objects.create(
            destination=self.destination, name="Located Stop", category="nature",
            description="Nature stop", estimated_cost=100, sustainability_score=80,
            crowd_level=20, latitude=12.0, longitude=76.0,
        )
        missing = Attraction.objects.create(
            destination=self.destination, name="Unlocated Stop", category="culture",
            description="Culture stop", estimated_cost=100, sustainability_score=60,
            crowd_level=60,
        )
        scores = {first.pk: 80, missing.pk: 60}
        with patch("travel.services.optimizer.recommendation_score", side_effect=lambda attraction, _trip, _ids: scores[attraction.pk]):
            comparison = itinerary_comparison_breakdown(self.trip, [first, missing], [first, missing])

        components = {item["key"]: item for item in comparison["components"]}
        self.assertFalse(components["route_compactness"]["available"])
        self.assertIn("coordinates", components["route_compactness"]["unavailable_reason"])
        self.assertFalse(comparison["route_available"])
        self.assertIsNone(comparison["route_distance_km"])
        self.assertIsNone(components["route_compactness"]["weighted_points"])
        self.assertAlmostEqual(sum(item["normalized_weight_percent"] for item in components.values() if item["available"]), 100)
        self.assertIsNotNone(comparison["quality_score"])

    def test_attraction_budget_feasibility_is_separate_from_quality_score(self):
        from .services.optimizer import itinerary_comparison_breakdown

        self.trip.budget = 500
        self.trip.travelers = 2
        self.trip.save(update_fields=["budget", "travelers"])
        first = Attraction.objects.create(
            destination=self.destination, name="Costly Stop A", category="nature",
            description="Nature", estimated_cost=100, sustainability_score=80,
            crowd_level=20, latitude=12.0, longitude=76.0,
        )
        second = Attraction.objects.create(
            destination=self.destination, name="Costly Stop B", category="culture",
            description="Culture", estimated_cost=200, sustainability_score=60,
            crowd_level=60, latitude=12.0, longitude=77.0,
        )
        scores = {first.pk: 80, second.pk: 60}
        with patch("travel.services.optimizer.recommendation_score", side_effect=lambda attraction, _trip, _ids: scores[attraction.pk]):
            comparison = itinerary_comparison_breakdown(self.trip, [first, second], [first, second])

        self.assertFalse(comparison["budget_feasible"])
        self.assertEqual(comparison["attraction_cost"], 600)
        self.assertGreater(comparison["quality_score"], 0)

    def test_comparison_matches_existing_nsga2_option_and_does_not_change_saved_itinerary(self):
        from .services.optimizer import itinerary_comparison_breakdown
        from .services.nsga2 import optimize_pareto

        second = Attraction.objects.create(
            destination=self.destination, name="Second Mysuru Stop", category="nature",
            description="Garden stop", estimated_cost=100, sustainability_score=85,
            crowd_level=30, latitude=12.31, longitude=76.65,
        )
        option = optimize_pareto(
            self.trip, [self.attraction, second], population_size=12, generations=2, alternatives=1
        )[0]
        comparison = itinerary_comparison_breakdown(
            self.trip, option["attractions"], [self.attraction, second]
        )
        before_items = list(self.trip.items.order_by("pk").values_list(
            "pk", "day_number", "attraction_id", "start_time", "end_time", "score", "reason"
        ))

        preference_component = next(
            item for item in comparison["components"] if item["key"] == "preference_match"
        )
        self.assertEqual(round(preference_component["score"], 1), option["preference_score"])
        self.assertEqual(comparison["attraction_cost"], option["estimated_cost"])
        self.assertEqual(comparison["selected_unique_count"], option["stop_count"])

        response = self.client.get(reverse("decision_lab", args=[self.trip.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Comparison quality score")
        self.assertContains(response, "View quality score components")
        self.assertContains(response, "Attraction budget fits")
        self.assertContains(response, "Lower crowd pressure")
        self.assertContains(response, "Weighted points")
        self.assertContains(response, "unique stops selected")
        self.trip.refresh_from_db()
        after_items = list(self.trip.items.order_by("pk").values_list(
            "pk", "day_number", "attraction_id", "start_time", "end_time", "score", "reason"
        ))
        self.assertEqual(after_items, before_items)

    def test_pdf_export_service_generates_pdf_bytes(self):
        from .services.pdf import trip_pdf
        output = trip_pdf(self.trip)
        self.assertEqual(output.read(4), b"%PDF")

    def test_pdf_export_handles_empty_itinerary_and_optional_stop_fields(self):
        from .services.pdf import trip_pdf

        empty_trip = Trip.objects.create(
            user=self.user,
            destination=self.destination,
            title="Empty itinerary & options",
            start_date=date(2026, 12, 1),
            end_date=date(2026, 12, 2),
            travelers=1,
            budget=5000,
        )
        empty_pdf = trip_pdf(empty_trip).getvalue()
        self.assertTrue(empty_pdf.startswith(b"%PDF"))
        self.assertGreater(len(empty_pdf), 1000)

        optional_stop = Attraction.objects.create(
            destination=self.destination,
            name="Café & Palace <North>",
            category="culture",
            description="A restored heritage site",
        )
        ItineraryItem.objects.create(
            trip=empty_trip,
            day_number=1,
            attraction=optional_stop,
            start_time=None,
            reason="",
            weather_alternative=None,
        )
        optional_pdf = trip_pdf(empty_trip).getvalue()
        self.assertTrue(optional_pdf.startswith(b"%PDF"))
        self.assertGreater(len(optional_pdf), 1000)

    def test_pdf_export_handles_long_names_many_days_and_expenses(self):
        from .services.pdf import trip_pdf

        destination = Destination.objects.create(
            name="Mysuru & Coorg Heritage and Nature Travel District",
            state="Karnataka & Western Ghats",
            description="A long destination description with <special> & characters.",
            average_daily_cost=1800,
        )
        trip = Trip.objects.create(
            user=self.user,
            destination=destination,
            title="A Long Family Journey & Cultural Exploration <2026>",
            start_date=date(2026, 12, 1),
            end_date=date(2026, 12, 10),
            travelers=4,
            budget=90000,
            interest="culture",
            pace="balanced",
        )
        alternatives = []
        for index in range(24):
            attraction = Attraction.objects.create(
                destination=destination,
                name=f"Café & Palace Garden Experience Number {index + 1} <North Wing>",
                category="culture" if index % 2 == 0 else "nature",
                description="A detailed description with ampersands & angle brackets <safe text>.",
                estimated_cost=125 + index,
                duration_hours=1.5,
            )
            alternatives.append(attraction)
            ItineraryItem.objects.create(
                trip=trip,
                day_number=index // 3 + 1,
                attraction=attraction,
                start_time=None if index % 4 == 0 else "10:30",
                score=82.5,
                reason=(
                    "A long recommendation explanation that wraps across several lines, "
                    "includes safe special characters such as <garden> & café, and stays readable. "
                ) * 3,
                weather_alternative=alternatives[index - 1] if index % 3 == 2 else None,
            )

        for index in range(30):
            BudgetExpense.objects.create(
                trip=trip,
                category="Transport" if index % 2 else "Food",
                amount="123.45",
                description=f"Long expense description {index + 1}: airport transfer & local travel <receipt reference>",
            )

        pdf_bytes = trip_pdf(trip).getvalue()

        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        self.assertGreater(len(pdf_bytes), 10000)

    def test_pdf_export_is_private_to_trip_owner(self):
        from django.contrib.auth.models import User

        other_user = User.objects.create_user(username="pdf-outsider", password="testpass123")
        url = reverse("export_trip_pdf", args=[self.trip.pk])

        self.client.force_login(other_user)
        denied = self.client.get(url)
        self.assertEqual(denied.status_code, 404)

        self.client.force_login(self.user)
        allowed = self.client.get(url)
        self.assertEqual(allowed.status_code, 200)
        self.assertEqual(allowed["Content-Type"], "application/pdf")

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
            "start_date": "2026-11-01",
            "end_date": "2026-11-01",
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

    def test_knapsack_can_select_free_activities_with_zero_budget(self):
        from types import SimpleNamespace
        from .services.knapsack import select_attractions_knapsack
        free = SimpleNamespace(id=1, name="Free park", estimated_cost=0)
        result = select_attractions_knapsack([free], budget=0, scores={1: 10})
        self.assertEqual(result["selected"], [free])
        self.assertEqual(result["total_cost"], 0)

    def test_missing_coordinates_are_not_zero_route_distance(self):
        from types import SimpleNamespace
        from .services.nsga2 import _distance
        mapped = SimpleNamespace(latitude=12.0, longitude=77.0)
        unmapped = SimpleNamespace(latitude=None, longitude=None)
        self.assertIsNone(_distance(mapped, unmapped))

    def test_pdf_text_is_xml_escaped(self):
        from .services.pdf import _xml
        self.assertEqual(_xml("<b>A&B</b>"), "&lt;b&gt;A&amp;B&lt;/b&gt;")

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

    def test_otp_refuses_console_backend_that_would_log_the_code(self):
        from django.test import override_settings
        from .services.otp import issue_otp
        user = User.objects.create_user(username="otp-console", email="console@example.com", password="testpass123")
        with override_settings(EMAIL_BACKEND="django.core.mail.backends.console.EmailBackend"):
            with self.assertRaises(RuntimeError):
                issue_otp(user, "register")
        self.assertFalse(OTPVerification.objects.filter(user=user, purpose="register").exists())


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
        self.assertIn("total_attractions", res_staff.context)
        self.assertIn("trip_trend", res_staff.context)
        self.assertFalse(res_staff.context["trip_trend_has_data"])
        self.assertContains(res_staff, "No trips were created in the last 12 months.")


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
            owner=self.owner, trip=self.trip, invite_code="TESTINVITE99",
            invite_expires_at=timezone.now() + timedelta(days=30),
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

    def test_get_invite_link_does_not_join_member_and_expired_invites_are_rejected(self):
        self.client.force_login(self.outsider)
        response = self.client.get(reverse("join_group_trip") + "?code=TESTINVITE99")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.group.members.filter(id=self.outsider.id).exists())
        self.group.invite_expires_at = timezone.now() - timedelta(seconds=1)
        self.group.save(update_fields=["invite_expires_at"])
        response = self.client.post(reverse("join_group_trip"), {"invite_code": "TESTINVITE99"})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.group.members.filter(id=self.outsider.id).exists())

    def test_group_vote_is_destination_scoped_and_repeat_submissions_are_idempotent(self):
        self.client.force_login(self.member)
        outside = Destination.objects.create(name="Other", state="Other", description="Other")
        outside_attraction = Attraction.objects.create(
            destination=outside, name="Unrelated", category="nature", description="Outside"
        )
        url = reverse("group", args=[self.trip.pk])
        bad = self.client.post(url, {"action": "vote", "attraction_id": outside_attraction.pk, "vote": "like"})
        self.assertEqual(bad.status_code, 404)
        self.assertFalse(RecommendationFeedback.objects.filter(trip=self.trip, user=self.member).exists())
        for _ in range(2):
            response = self.client.post(url, {"action": "vote", "attraction_id": self.attraction2.pk, "vote": "like"})
            self.assertEqual(response.status_code, 302)
        self.assertEqual(RecommendationFeedback.objects.filter(trip=self.trip, user=self.member, attraction=self.attraction2).count(), 1)
        self.member.refresh_from_db()
        self.assertAlmostEqual(self.member.preference.nature, 0.58)

    def test_group_vote_rejects_malformed_input_without_creating_feedback(self):
        self.client.force_login(self.member)
        url = reverse("group", args=[self.trip.pk])

        malformed_id = self.client.post(url, {
            "action": "vote", "attraction_id": "not-an-id", "vote": "like",
        })
        invalid_choice = self.client.post(url, {
            "action": "vote", "attraction_id": self.attraction2.pk, "vote": "maybe",
        })

        self.assertEqual(malformed_id.status_code, 302)
        self.assertEqual(invalid_choice.status_code, 302)
        self.assertFalse(RecommendationFeedback.objects.filter(trip=self.trip).exists())

    def test_duplicate_join_is_idempotent_and_missing_expiry_is_rejected(self):
        self.client.force_login(self.member)
        url = reverse("join_group_trip")

        first_join = self.client.post(url, {"invite_code": "TESTINVITE99"})
        second_join = self.client.post(url, {"invite_code": "TESTINVITE99"})
        self.assertEqual(first_join.status_code, 302)
        self.assertEqual(second_join.status_code, 302)
        self.assertEqual(self.group.members.filter(pk=self.member.pk).count(), 1)

        self.group.members.remove(self.member)
        self.group.invite_expires_at = None
        self.group.save(update_fields=["invite_expires_at"])
        expired = self.client.post(url, {"invite_code": "TESTINVITE99"})
        self.assertEqual(expired.status_code, 200)
        self.assertFalse(self.group.members.filter(pk=self.member.pk).exists())

    def test_only_host_can_manage_members_or_optimize_group_trip(self):
        self.client.force_login(self.member)
        url = reverse("group", args=[self.trip.pk])
        original_code = self.group.invite_code
        original_items = list(self.trip.items.order_by("id").values_list("id", "attraction_id"))

        for payload in (
            {"action": "add", "username": self.outsider.username},
            {"action": "remove", "member_id": self.member.pk},
            {"action": "renew_invite"},
            {"action": "optimize"},
        ):
            response = self.client.post(url, payload)
            self.assertEqual(response.status_code, 302)

        self.assertFalse(self.group.members.filter(pk=self.outsider.pk).exists())
        self.assertTrue(self.group.members.filter(pk=self.member.pk).exists())
        self.group.refresh_from_db()
        self.assertEqual(self.group.invite_code, original_code)
        self.assertEqual(
            list(self.trip.items.order_by("id").values_list("id", "attraction_id")),
            original_items,
        )

    def test_outsider_cannot_modify_group_and_empty_or_tied_votes_are_neutral(self):
        url = reverse("group", args=[self.trip.pk])
        self.client.force_login(self.outsider)
        response = self.client.post(url, {
            "action": "vote", "attraction_id": self.attraction1.pk, "vote": "like",
        })
        self.assertEqual(response.status_code, 302)
        self.assertFalse(RecommendationFeedback.objects.filter(trip=self.trip).exists())

        self.client.force_login(self.owner)
        captured = []

        def capture_group_preferences(trip, user):
            captured.append((
                set(getattr(trip, "_group_feedback_ids", set())),
                set(getattr(trip, "_disliked_attraction_ids", set())),
            ))

        with patch("travel.views._build_itinerary", side_effect=capture_group_preferences):
            self.client.post(url, {"action": "optimize"})
            RecommendationFeedback.objects.create(
                user=self.owner, trip=self.trip, attraction=self.attraction1, action="like"
            )
            RecommendationFeedback.objects.create(
                user=self.member, trip=self.trip, attraction=self.attraction1, action="dislike"
            )
            self.client.post(url, {"action": "optimize"})

        self.assertEqual(captured, [(set(), set()), (set(), set())])
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.interest, "history")

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

    def test_budget_manali_example_formulas_keep_categories_separate(self):
        from decimal import Decimal

        self.client.force_login(self.owner)
        self.trip.budget = 70000
        self.trip.save(update_fields=["budget"])
        url = reverse("budget", args=[self.trip.pk])
        for category, amount, description in (
            ("Food", "1200.00", "Meals"),
            ("Transport", "14000.00", "Transfers"),
        ):
            added = self.client.post(url, {
                "category": category,
                "amount": amount,
                "description": description,
            })
            self.assertEqual(added.status_code, 302)

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total"], Decimal("15200.00"))
        self.assertEqual(response.context["remaining"], 54800)
        self.assertEqual(response.context["daily_burn_rate"], 3800)
        self.assertEqual(response.context["target_daily_budget"], 17500)
        self.assertEqual(response.context["spending_percentage"], 22)
        self.assertEqual(
            list(BudgetExpense.objects.filter(trip=self.trip).order_by("category").values_list("category", "amount")),
            [("Food", Decimal("1200.00")), ("Transport", Decimal("14000.00"))],
        )

        categories = {item["key"]: item for item in response.context["planned_vs_actual"]}
        self.assertEqual(categories["Food"]["planned"], 17500)
        self.assertEqual(categories["Food"]["actual"], Decimal("1200.00"))
        self.assertEqual(categories["Food"]["pct_used"], 7)
        self.assertEqual(categories["Food"]["diff"], Decimal("16300.00"))
        self.assertEqual(categories["Food"]["status_text"], "On Track")
        self.assertEqual(categories["Transport"]["planned"], 14000)
        self.assertEqual(categories["Transport"]["actual"], Decimal("14000.00"))
        self.assertFalse(categories["Transport"]["is_over"])
        self.assertEqual(categories["Transport"]["status_text"], "Near Limit")
        self.assertEqual(categories["Transport"]["diff"], Decimal("0.00"))
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.food_budget_pct, 25)
        self.assertEqual(self.trip.transport_budget_pct, 20)

    def test_budget_category_zero_exact_limit_and_overspend_statuses(self):
        from decimal import Decimal

        self.client.force_login(self.owner)
        url = reverse("budget", args=[self.trip.pk])
        zero_response = self.client.get(url)
        food = next(item for item in zero_response.context["planned_vs_actual"] if item["key"] == "Food")
        self.assertEqual(food["pct_used"], 0)
        self.assertEqual(food["status_text"], "On Track")
        self.assertEqual(food["diff"], 6250)

        expense = BudgetExpense.objects.create(
            trip=self.trip, category="Food", amount="6250.00", description="At allocation limit"
        )
        exact_response = self.client.get(url)
        food = next(item for item in exact_response.context["planned_vs_actual"] if item["key"] == "Food")
        self.assertFalse(food["is_over"])
        self.assertEqual(food["pct_used"], 100)
        self.assertEqual(food["status_text"], "Near Limit")
        self.assertEqual(food["diff"], Decimal("0.00"))

        expense.amount = Decimal("6250.01")
        expense.save(update_fields=["amount"])
        over_response = self.client.get(url)
        food = next(item for item in over_response.context["planned_vs_actual"] if item["key"] == "Food")
        self.assertTrue(food["is_over"])
        self.assertEqual(food["pct_used"], 100)
        self.assertEqual(food["status_text"], "Over Budget")
        self.assertEqual(food["diff"], Decimal("0.01"))

    def test_budget_zero_allocation_handles_zero_and_nonzero_spending(self):
        self.client.force_login(self.owner)
        self.trip.accommodation_budget_pct = 100
        self.trip.food_budget_pct = 0
        self.trip.transport_budget_pct = 0
        self.trip.activities_budget_pct = 0
        self.trip.miscellaneous_budget_pct = 0
        self.trip.save()

        url = reverse("budget", args=[self.trip.pk])
        response = self.client.get(url)
        food = next(item for item in response.context["planned_vs_actual"] if item["key"] == "Food")
        self.assertEqual(food["pct_used"], 0)
        self.assertEqual(food["status_text"], "On Track")
        BudgetExpense.objects.create(trip=self.trip, category="Food", amount="0.01")
        response = self.client.get(url)
        food = next(item for item in response.context["planned_vs_actual"] if item["key"] == "Food")
        self.assertEqual(food["pct_used"], 100)
        self.assertTrue(food["is_over"])
        self.assertEqual(food["status_text"], "Over Budget")

    def test_budget_chart_has_data_and_cdn_failure_fallback(self):
        self.client.force_login(self.owner)
        BudgetExpense.objects.create(trip=self.trip, category="Food", amount="1200.00")
        BudgetExpense.objects.create(trip=self.trip, category="Transport", amount="14000.00")
        response = self.client.get(reverse("budget", args=[self.trip.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, '<canvas id="expenseCategoryChart"></canvas>', html=True)
        self.assertContains(response, 'id="expenseCategoryChartFallback"')
        self.assertContains(response, 'id="expenseCategoryChartFallbackList"')
        self.assertContains(response, "Chart visualization is unavailable.")
        self.assertContains(response, "Food")
        self.assertContains(response, "Transport")
        self.assertContains(response, 'id="expense-category-labels" type="application/json"')
        self.assertContains(response, 'id="expense-category-amounts" type="application/json"')
        self.assertIn('typeof Chart !== "undefined"', response.content.decode())
        self.assertIn('chartCanvas.parentElement.hidden = true', response.content.decode())

    def test_budget_allocations_validate_total_and_save_without_creating_expenses(self):
        self.client.force_login(self.owner)
        url = reverse("budget", args=[self.trip.pk])
        invalid = self.client.post(url, {
            "action": "save_allocations", "accommodation_budget_pct": 40,
            "food_budget_pct": 25, "transport_budget_pct": 20,
            "activities_budget_pct": 10, "miscellaneous_budget_pct": 4,
        })
        self.assertEqual(invalid.status_code, 200)
        self.assertFalse(BudgetExpense.objects.filter(trip=self.trip).exists())
        valid = self.client.post(url, {
            "action": "save_allocations", "accommodation_budget_pct": 40,
            "food_budget_pct": 20, "transport_budget_pct": 20,
            "activities_budget_pct": 15, "miscellaneous_budget_pct": 5,
        })
        self.assertEqual(valid.status_code, 302)
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.accommodation_budget_pct, 40)
        response = self.client.get(url)
        targets = response.context["planned_vs_actual"]
        self.assertEqual(sum(item["planned"] for item in targets), self.trip.budget)

    def test_expense_form_accepts_cents_and_allocation_form_requires_one_hundred_percent(self):
        from .forms import BudgetAllocationForm, ExpenseForm
        self.assertTrue(ExpenseForm({"category": "Food", "amount": "12.50", "description": "Tea"}).is_valid())
        values = {"accommodation_budget_pct": 35, "food_budget_pct": 25, "transport_budget_pct": 20, "activities_budget_pct": 15, "miscellaneous_budget_pct": 5}
        self.assertTrue(BudgetAllocationForm(values).is_valid())
        values["miscellaneous_budget_pct"] = 4
        self.assertFalse(BudgetAllocationForm(values).is_valid())

    def test_budget_access_defaults_empty_totals_and_zero_budget(self):
        url = reverse("budget", args=[self.trip.pk])
        self.assertEqual(self.client.get(url).status_code, 302)

        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(url).status_code, 404)

        self.client.force_login(self.owner)
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["total"], 0)
        self.assertEqual(response.context["remaining"], self.trip.budget)
        self.assertEqual(response.context["spending_percentage"], 0)
        self.assertEqual(sum(item["planned"] for item in response.context["planned_vs_actual"]), self.trip.budget)
        self.assertEqual(response.context["allocation_form"].initial["accommodation_budget_pct"], 35)
        self.assertEqual(response.context["allocation_form"].initial["food_budget_pct"], 25)

        zero_trip = Trip.objects.create(
            user=self.owner,
            destination=self.destination,
            title="Zero budget",
            start_date=date(2026, 11, 1),
            end_date=date(2026, 11, 1),
            travelers=1,
            budget=0,
        )
        zero_response = self.client.get(reverse("budget", args=[zero_trip.pk]))
        self.assertEqual(zero_response.status_code, 200)
        self.assertEqual(zero_response.context["remaining"], 0)
        self.assertEqual(zero_response.context["spending_percentage"], 0)
        self.assertEqual(sum(item["planned"] for item in zero_response.context["planned_vs_actual"]), 0)
        BudgetExpense.objects.create(
            trip=zero_trip, category="Food", amount="0.01", description="Spending with zero budget"
        )
        spent_zero_response = self.client.get(reverse("budget", args=[zero_trip.pk]))
        self.assertEqual(spent_zero_response.context["remaining"], 0)
        self.assertEqual(spent_zero_response.context["spending_percentage"], 100)
        self.assertTrue(any("exceeded your trip budget" in item for item in spent_zero_response.context["spending_insights"]))

    def test_budget_allocation_boundary_values_persist_without_expenses(self):
        self.client.force_login(self.owner)
        response = self.client.post(reverse("budget", args=[self.trip.pk]), {
            "action": "save_allocations",
            "accommodation_budget_pct": 100,
            "food_budget_pct": 0,
            "transport_budget_pct": 0,
            "activities_budget_pct": 0,
            "miscellaneous_budget_pct": 0,
        })
        self.assertEqual(response.status_code, 302)
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.accommodation_budget_pct, 100)
        self.assertEqual(self.trip.food_budget_pct, 0)
        self.assertFalse(BudgetExpense.objects.filter(trip=self.trip).exists())

        refreshed = self.client.get(reverse("budget", args=[self.trip.pk]))
        self.assertEqual(refreshed.context["allocation_form"]["accommodation_budget_pct"].value(), 100)
        self.assertEqual(refreshed.context["allocation_form"]["food_budget_pct"].value(), 0)
        self.assertEqual(sum(item["planned"] for item in refreshed.context["planned_vs_actual"]), self.trip.budget)

    def test_expense_submission_validates_amount_and_updates_over_budget_totals(self):
        from decimal import Decimal

        self.client.force_login(self.owner)
        url = reverse("budget", args=[self.trip.pk])
        invalid_amounts = ["0", "-1", "not-a-number", "10000000000.00"]
        for amount in invalid_amounts:
            response = self.client.post(url, {
                "category": "Food",
                "amount": amount,
                "description": "Invalid amount test",
            })
            self.assertEqual(response.status_code, 200)
            self.assertTrue(response.context["form"].errors)
            self.assertFalse(BudgetExpense.objects.filter(trip=self.trip).exists())

        invalid_category = self.client.post(url, {
            "category": "Not a category",
            "amount": "10.00",
            "description": "Invalid category test",
        })
        self.assertEqual(invalid_category.status_code, 200)
        self.assertFalse(BudgetExpense.objects.filter(trip=self.trip).exists())

        saved = self.client.post(url, {
            "category": "Food",
            "amount": "25000.50",
            "description": "Trip meals",
        })
        self.assertEqual(saved.status_code, 302)
        expense = BudgetExpense.objects.get(trip=self.trip)
        self.assertEqual(expense.amount, Decimal("25000.50"))
        self.assertEqual(expense.category, "Food")

        refreshed = self.client.get(url)
        self.assertEqual(refreshed.context["total"], Decimal("25000.50"))
        self.assertEqual(refreshed.context["remaining"], 0)
        self.assertEqual(refreshed.context["spending_percentage"], 100)
        food = next(item for item in refreshed.context["planned_vs_actual"] if item["key"] == "Food")
        self.assertEqual(food["actual"], Decimal("25000.50"))
        self.assertTrue(food["is_over"])
        self.assertTrue(any("exceeded your trip budget" in item for item in refreshed.context["spending_insights"]))
        self.assertEqual(self.trip.accommodation_budget_pct, 35)

    def test_expense_edit_delete_and_cross_user_boundaries(self):
        expense = BudgetExpense.objects.create(
            trip=self.trip,
            category="Food",
            amount="12.50",
            description="Lunch",
        )
        other_trip = Trip.objects.create(
            user=self.outsider,
            destination=self.destination,
            title="Another user's trip",
            start_date=date(2026, 11, 1),
            end_date=date(2026, 11, 1),
            travelers=1,
            budget=1000,
        )
        other_expense = BudgetExpense.objects.create(
            trip=other_trip,
            category="Transport",
            amount="20.00",
            description="Taxi",
        )
        self.client.force_login(self.outsider)
        self.assertEqual(self.client.get(reverse("budget", args=[self.trip.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("budget_expense_edit", args=[self.trip.pk, expense.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("budget_expense_delete", args=[self.trip.pk, expense.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("budget_expense_edit", args=[other_trip.pk, expense.pk])).status_code, 404)
        expense.refresh_from_db()

        self.client.force_login(self.owner)
        edit_url = reverse("budget_expense_edit", args=[self.trip.pk, expense.pk])
        self.assertEqual(self.client.get(edit_url).status_code, 200)
        invalid = self.client.post(edit_url, {})
        self.assertEqual(invalid.status_code, 200)
        self.assertTrue(invalid.context["form"].is_bound)
        self.assertTrue(invalid.context["form"].errors)
        expense.refresh_from_db()
        self.assertEqual(expense.amount, 12.50)

        updated = self.client.post(edit_url, {
            "category": "Transport",
            "amount": "23.75",
            "description": "Airport taxi",
        })
        self.assertEqual(updated.status_code, 302)
        expense.refresh_from_db()
        self.assertEqual(expense.amount, 23.75)
        self.assertEqual(expense.category, "Transport")

        delete_url = reverse("budget_expense_delete", args=[self.trip.pk, expense.pk])
        self.assertEqual(self.client.get(delete_url).status_code, 405)
        deleted = self.client.post(delete_url)
        self.assertEqual(deleted.status_code, 302)
        self.assertFalse(BudgetExpense.objects.filter(pk=expense.pk).exists())
        self.assertTrue(BudgetExpense.objects.filter(pk=other_expense.pk).exists())

    def test_invitation_is_random_and_get_does_not_create_a_group(self):
        self.client.force_login(self.owner)
        self.group.delete()
        response = self.client.get(reverse("group", args=[self.trip.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(GroupTrip.objects.filter(trip=self.trip).exists())
        self.client.post(reverse("group", args=[self.trip.pk]), {"action": "create_group"})
        group = GroupTrip.objects.get(trip=self.trip)
        self.assertGreaterEqual(len(group.invite_code), 20)
        self.assertTrue(group.invite_expires_at > timezone.now())

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
        self.assertEqual(res.context["total_attractions"], 2)
        self.assertEqual(sum(item["count"] for item in res.context["trip_trend"]), 1)
        self.assertTrue(res.context["trip_trend_has_data"])
        self.assertEqual(res.context["popular_chart"], [{"label": "Udaipur", "count": 1}])
        self.assertContains(res, "Trip creation trend")
        self.assertContains(res, "Most planned destinations")
        self.assertContains(res, "analytics-trip-trend")
        self.assertContains(res, "Total Attractions")


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
        self.assertContains(response, "copilot-route-points-data")
        self.assertContains(response, "leaflet@1.9.4/dist/leaflet.js")
        self.assertContains(response, "/static/travel/js/copilot-map.js")
        self.assertEqual(response.context["map_config"]["tile_attribution"], "Example map provider")

    def test_copilot_map_excludes_missing_and_invalid_coordinates(self):
        from unittest.mock import patch

        self.attr_paid.latitude = 26.9855
        self.attr_paid.longitude = 75.8513
        self.attr_paid.save(update_fields=["latitude", "longitude"])
        invalid_attraction = Attraction.objects.create(
            destination=self.destination,
            name="Invalid Coordinate Stop",
            category="nature",
            description="Coordinates outside the valid range",
            latitude=95,
            longitude=181,
        )
        ItineraryItem.objects.create(
            trip=self.trip,
            day_number=2,
            attraction=invalid_attraction,
            start_time="14:00",
        )
        self.client.force_login(self.user)

        with patch("travel.views.weather_context", return_value={"condition": "Clear", "source": "Test"}):
            response = self.client.get(reverse("trip_copilot_detail", args=[self.trip.pk]))

        self.assertEqual(response.status_code, 200)
        route_points = response.context["route_points"]
        self.assertEqual([point["name"] for point in route_points], ["Amber Fort"])
        self.assertEqual(route_points[0]["lat"], 26.9855)
        self.assertEqual(route_points[0]["lon"], 75.8513)
        self.assertContains(response, "Some scheduled stops do not have valid coordinates")

    def test_copilot_map_shows_empty_state_when_no_stops_have_coordinates(self):
        from unittest.mock import patch

        self.client.force_login(self.user)
        with patch("travel.views.weather_context", return_value={"condition": "Clear", "source": "Test"}):
            response = self.client.get(reverse("trip_copilot_detail", args=[self.trip.pk]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["route_points"], [])
        self.assertContains(response, "No scheduled stops have valid map coordinates.")
        self.assertContains(response, "Attraction latitude and longitude are needed")

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

    def test_copilot_invalid_creation_parameters_do_not_reach_optimizer_or_create_trip(self):
        from unittest.mock import patch

        self.client.force_login(self.user)
        trip_count = Trip.objects.count()
        with patch("travel.views.generate_copilot_alternatives", return_value=[]) as generate:
            response = self.client.post(reverse("trip_copilot"), {
                "action": "create_from_alternative",
                "destination": self.destination.pk,
                "days": "999999999",
                "budget": "10000",
                "travelers": "2",
                "interest": "history",
                "pace": "balanced",
                "alternative_key": "budget_saver",
            })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Trip.objects.count(), trip_count)
        self.assertTrue(all(call.args[1] == 3 for call in generate.call_args_list))
        self.assertContains(response, "Trip duration must be from 1 to 30 days")

    def test_copilot_does_not_create_a_trip_when_no_alternative_has_stops(self):
        from unittest.mock import patch

        self.client.force_login(self.user)
        trip_count = Trip.objects.count()
        with patch("travel.views.generate_copilot_alternatives", return_value=[]):
            response = self.client.post(reverse("trip_copilot"), {
                "action": "create_from_alternative",
                "destination": self.destination.pk,
                "days": "2",
                "budget": "10000",
                "travelers": "2",
                "interest": "history",
                "pace": "balanced",
                "alternative_key": "budget_saver",
            })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(Trip.objects.count(), trip_count)
        self.assertContains(response, "That alternative has no schedulable activities")

    def test_copilot_trip_creation_rolls_back_if_itinerary_insert_fails(self):
        from django.db import IntegrityError
        from unittest.mock import patch

        self.client.force_login(self.user)
        trip_count = Trip.objects.count()
        alternative = {
            "key": "budget_saver",
            "title": "Budget Saver",
            "stop_count": 1,
            "days": [{
                "day_number": 1,
                "items": [{
                    "attraction": self.attr_paid,
                    "time": "09:00",
                    "end_time": "12:00",
                    "score": 75,
                    "reason": "Test selection",
                }],
            }],
        }
        with (
            patch("travel.views.generate_copilot_alternatives", return_value=[alternative]),
            patch("travel.views.ItineraryItem.objects.bulk_create", side_effect=IntegrityError("simulated insert failure")),
            self.assertRaises(IntegrityError),
        ):
            self.client.post(reverse("trip_copilot"), {
                "action": "create_from_alternative",
                "destination": self.destination.pk,
                "days": "2",
                "budget": "10000",
                "travelers": "2",
                "interest": "history",
                "pace": "balanced",
                "alternative_key": "budget_saver",
                "title": "Rollback Trip",
            })

        self.assertEqual(Trip.objects.count(), trip_count)
        self.assertFalse(Trip.objects.filter(title="Rollback Trip").exists())

    def test_copilot_conversational_refinement_relaxed(self):
        self.trip.items.filter(attraction=self.attr_gem).update(day_number=1)
        ItineraryItem.objects.create(
            trip=self.trip, day_number=1, attraction=self.attr_free, score=60.0
        )
        self.client.force_login(self.user)
        res = self.client.post(reverse("trip_copilot_detail", args=[self.trip.pk]), {
            "action": "refine",
            "prompt": "Make the itinerary more relaxed with unhurried visits",
        })
        self.assertEqual(res.status_code, 302)
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.pace, "relaxed")
        self.assertEqual(self.trip.items.filter(day_number=1).count(), 2)
        self.assertFalse(self.trip.items.filter(attraction=self.attr_free).exists())
        self.assertTrue(self.trip.items.filter(attraction=self.attr_paid).exists())
        self.assertTrue(self.trip.items.filter(attraction=self.attr_gem).exists())

    def test_copilot_conversational_refinement_budget(self):
        original_ids = list(self.trip.items.order_by("pk").values_list("pk", flat=True))
        res = refine_itinerary_with_prompt(self.trip, "Reduce the budget and swap for free attractions")
        self.assertTrue(res["success"])
        self.assertEqual(res["action_type"], "budget_cut")
        self.assertIn("Budget optimized", res["summary"])
        replacement_names = {item["attraction"].name for item in res["repaired_items"]}
        self.assertIn("Jal Mahal Viewpoint", replacement_names)
        self.assertEqual(list(self.trip.items.order_by("pk").values_list("pk", flat=True)), original_ids)

    def test_copilot_budget_refinement_reports_when_no_free_alternative_exists(self):
        self.attr_free.estimated_cost = 300
        self.attr_free.save(update_fields=["estimated_cost"])
        self.attr_extra_free.estimated_cost = 400
        self.attr_extra_free.save(update_fields=["estimated_cost"])

        result = refine_itinerary_with_prompt(self.trip, "Reduce the budget and swap for free attractions")

        self.assertEqual(result["action_type"], "budget_cut")
        self.assertEqual(result["changes"], [])
        self.assertIn("No unused free-at-entry alternative was available", result["summary"])
        self.assertEqual(
            [item["attraction"].id for item in result["repaired_items"]],
            list(self.trip.items.order_by("day_number", "start_time", "pk").values_list("attraction_id", flat=True)),
        )

    def test_copilot_refinement_handles_empty_saved_itinerary(self):
        self.trip.items.all().delete()

        result = refine_itinerary_with_prompt(self.trip, "Add more nature activities")

        self.assertFalse(result["success"])
        self.assertEqual(result["action_type"], "no_itinerary")
        self.assertIn("Generate a trip plan first", result["summary"])
        self.assertEqual(result["repaired_items"], [])

    def test_copilot_interest_refinement_preview_is_pure_and_explicit_post_applies_it(self):
        original_ids = list(self.trip.items.order_by("pk").values_list("pk", flat=True))
        preview = refine_itinerary_with_prompt(self.trip, "Add more nature activities")
        self.assertEqual(preview["action_type"], "more_nature")
        self.assertTrue(any(item["attraction"].category == "nature" for item in preview["repaired_items"]))
        self.assertEqual(list(self.trip.items.order_by("pk").values_list("pk", flat=True)), original_ids)

        self.client.force_login(self.user)
        response = self.client.post(reverse("trip_copilot_detail", args=[self.trip.pk]), {
            "action": "refine",
            "prompt": "Add more nature activities",
        })
        self.assertEqual(response.status_code, 302)
        self.assertTrue(self.trip.items.filter(attraction__category="nature").exists())
        self.assertFalse(self.trip.items.filter(attraction=self.attr_paid).exists())

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
        self.assertEqual(list(res.context["destinations"]), [])
        self.assertContains(res, "Your comparison starts here")

        # Test with query params
        res_filtered = self.client.get(reverse("compare_destinations") + f"?ids={self.dest1.id}&ids={self.dest2.id}")
        self.assertEqual(res_filtered.status_code, 200)
        self.assertContains(res_filtered, "Jaipur")
        self.assertContains(res_filtered, "Udaipur")
        self.assertEqual([d.pk for d in res_filtered.context["destinations"]], [self.dest1.pk, self.dest2.pk])
        optional_blank = self.client.get(
            reverse("compare_destinations"),
            {"compare": "1", "ids": [self.dest1.pk, self.dest2.pk, ""]},
        )
        self.assertEqual([d.pk for d in optional_blank.context["destinations"]], [self.dest1.pk, self.dest2.pk])

        self.client.logout()
        anonymous_response = self.client.get(reverse("compare_destinations"))
        self.assertEqual(anonymous_response.status_code, 302)

    def test_comparison_shows_stored_images_cost_attraction_categories_and_reviews(self):
        Attraction.objects.create(destination=self.dest1, name="Palace", category="history", description="Historic palace")
        Attraction.objects.create(destination=self.dest1, name="Museum", category="history", description="Local museum")
        Attraction.objects.create(destination=self.dest1, name="Market", category="food", description="Food market")
        Attraction.objects.create(destination=self.dest2, name="Lake", category="nature", description="Lakefront")
        Review.objects.create(user=self.user, destination=self.dest1, rating=5, body="Excellent")

        response = self.client.get(
            reverse("compare_destinations"),
            {"compare": "1", "ids": [self.dest1.pk, self.dest2.pk]},
        )

        self.assertEqual(response.status_code, 200)
        jaipur, udaipur = response.context["destinations"]
        self.assertEqual(jaipur.attraction_count, 3)
        self.assertEqual(jaipur.attraction_categories, [{"name": "food", "count": 1}, {"name": "history", "count": 2}])
        self.assertEqual(jaipur.review_count, 1)
        self.assertEqual(udaipur.attraction_count, 1)
        self.assertContains(response, "Average daily cost")
        self.assertContains(response, "₹2,500")
        self.assertContains(response, "Attraction categories")
        self.assertContains(response, "History")
        self.assertContains(response, "Scenery in Jaipur, Rajasthan")
        self.assertContains(response, "Scenery in Udaipur, Rajasthan")
        self.assertNotContains(response, "Destination recommendation score")

    def test_comparison_rejects_duplicate_invalid_incomplete_and_unavailable_ids(self):
        cases = [
            ([""], "Choose two or three distinct destinations"),
            ([self.dest1.pk], "Choose two or three distinct destinations"),
            ([self.dest1.pk, self.dest1.pk], "Choose each destination only once"),
            ([self.dest1.pk, "not-an-id"], "selections are invalid"),
            ([self.dest1.pk, 999999], "no longer available"),
            ([self.dest1.pk, self.dest2.pk, self.dest1.pk, self.dest2.pk], "Choose two or three distinct destinations"),
        ]
        for ids, expected_error in cases:
            with self.subTest(ids=ids):
                response = self.client.get(reverse("compare_destinations"), {"compare": "1", "ids": ids})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(list(response.context["destinations"]), [])
                self.assertContains(response, expected_error)

    def test_recommendation_breakdown_shows_only_real_applied_positive_and_negative_factors(self):
        attraction = Attraction.objects.create(
            destination=self.dest1,
            name="Jaipur History Museum",
            category="history",
            description="A historic museum and palace collection",
            estimated_cost=200,
            duration_hours=1.5,
            sustainability_score=80,
            hidden_gem_score=70,
            crowd_level=30,
        )
        response = self.client.get(reverse("recommendations"), {
            "destination": self.dest1.pk,
            "interest": "history",
            "pace": "relaxed",
        })
        self.assertEqual(response.status_code, 200)
        breakdown = response.context["recommendations"][0][0].score_breakdown
        self.assertContains(response, "recommendation-score")
        self.assertContains(response, "Raw score:")
        self.assertContains(response, "Displayed match:")
        self.assertContains(response, "Interest match baseline")
        self.assertContains(response, "Sustainability score weighted by trip priority")
        self.assertContains(response, "Hidden-gem score enabled for this trip")
        self.assertContains(response, "Lower-crowd factor")
        self.assertContains(response, "Relaxed-pace duration fit")
        component_labels = [item["label"] for item in breakdown["components"]]
        self.assertNotIn("Positive attraction feedback", component_labels)
        self.assertNotIn("Low entry-cost adjustment", component_labels)

        RecommendationFeedback.objects.create(user=self.user, attraction=attraction, action="dislike")
        response = self.client.get(reverse("recommendations"), {
            "destination": self.dest1.pk,
            "interest": "history",
            "pace": "relaxed",
        })
        self.assertContains(response, "Negative attraction feedback")
        self.assertContains(response, "is-negative")
        disliked = next(item for item in response.context["recommendations"] if item[0].pk == attraction.pk)
        negative_feedback = next(
            item for item in disliked[0].score_breakdown["components"]
            if item["label"] == "Negative attraction feedback"
        )
        self.assertEqual(negative_feedback["value"], -18)

    def test_comparison_supports_three_distinct_destinations(self):
        third = Destination.objects.create(
            name="Jodhpur", state="Rajasthan", description="Blue City", average_daily_cost=2200
        )
        response = self.client.get(
            reverse("compare_destinations"),
            {"compare": "1", "ids": [self.dest1.pk, self.dest2.pk, third.pk]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item.pk for item in response.context["destinations"]], [self.dest1.pk, self.dest2.pk, third.pk])
        self.assertContains(response, "Jodhpur")

    def test_what_if_scenario_simulation_renders_outcome(self):
        from .models import WhatIfScenario

        attraction = Attraction.objects.create(
            destination=self.dest1,
            name="Jaipur Museum",
            category="history",
            description="A saved activity",
            estimated_cost=0,
        )
        original_item = ItineraryItem.objects.create(
            trip=self.trip, day_number=1, attraction=attraction, start_time="09:00"
        )
        url = reverse("what_if", args=[self.trip.pk])

        # GET request
        res_get = self.client.get(url)
        self.assertEqual(res_get.status_code, 200)
        self.assertContains(res_get, "What-If Trip Planning")
        self.assertEqual(res_get.context["form"]["preferred_interest"].value(), self.trip.interest)
        self.assertEqual(res_get.context["form"]["pace"].value(), self.trip.pace)

        invalid = self.client.post(url, {
            "name": "Invalid budget scenario",
            "budget_change": "not-a-budget",
            "extra_days": 1,
            "preferred_interest": "culture",
            "pace": "balanced",
        })
        self.assertEqual(invalid.status_code, 200)
        self.assertTrue(invalid.context["form"].errors)
        self.assertEqual(WhatIfScenario.objects.filter(trip=self.trip).count(), 0)
        self.assertEqual(list(self.trip.items.values_list("pk", flat=True)), [original_item.pk])

        invalid_interest = self.client.post(url, {
            "name": "Invalid interest scenario",
            "budget_change": 1000,
            "extra_days": 0,
            "preferred_interest": "made-up-interest",
            "pace": "balanced",
        })
        self.assertEqual(invalid_interest.status_code, 200)
        self.assertTrue(invalid_interest.context["form"].errors)
        self.assertEqual(WhatIfScenario.objects.filter(trip=self.trip).count(), 0)

        # POST simulation
        res_post = self.client.post(url, {
            "name": "Extended Budget Simulation",
            "budget_change": -20000,
            "extra_days": 1,
            "preferred_interest": "nature",
            "pace": "relaxed",
        })
        self.assertEqual(res_post.status_code, 200)
        self.assertContains(res_post, "Simulation Outcome")
        self.assertContains(res_post, "Simulated Budget")
        self.assertContains(res_post, "Suggested itinerary preview")
        self.assertContains(res_post, "Jaipur Museum")
        self.assertFalse(res_post.context["result"]["feasible"])
        self.assertEqual(res_post.context["result"]["budget"], 0)
        self.assertEqual(res_post.context["result"]["interest"], "nature")
        self.assertEqual(res_post.context["result"]["pace"], "relaxed")
        self.assertEqual(WhatIfScenario.objects.get(trip=self.trip).preferred_interest, "nature")
        self.trip.refresh_from_db()
        self.assertEqual(self.trip.budget, 15000)
        self.assertEqual(self.trip.interest, "culture")
        self.assertEqual(list(self.trip.items.values_list("pk", flat=True)), [original_item.pk])

    def test_what_if_empty_destination_displays_no_itinerary_without_saving_trip_changes(self):
        empty_destination = Destination.objects.create(
            name="Empty Jaipur", state="Rajasthan", description="No attraction records",
            average_daily_cost=1000,
        )
        empty_trip = Trip.objects.create(
            user=self.user, destination=empty_destination, title="Empty trip",
            start_date=date(2026, 11, 1), end_date=date(2026, 11, 1),
            travelers=1, budget=5000, interest="culture", pace="balanced",
        )

        response = self.client.post(reverse("what_if", args=[empty_trip.pk]), {
            "name": "No attraction scenario",
            "budget_change": 0,
            "extra_days": 0,
            "preferred_interest": "",
            "pace": "",
        })

        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["result"]["feasible"])
        self.assertFalse(response.context["result"]["has_itinerary"])
        self.assertContains(response, "No Itinerary Available")
        self.assertContains(response, "No valid itinerary is available")
        empty_trip.refresh_from_db()
        self.assertEqual(empty_trip.days, 1)
        self.assertEqual(empty_trip.budget, 5000)
        self.assertEqual(empty_trip.items.count(), 0)

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


class SeedDataCommandTests(TestCase):
    def _run_seed_data(self):
        from io import StringIO
        from django.core.management import call_command

        call_command("seed_data", stdout=StringIO())

    def test_seed_data_is_idempotent_and_preserves_existing_records(self):
        existing_destination = Destination.objects.create(
            name="Bengaluru", state="Legacy state", description="Existing row", best_for="culture"
        )
        existing_attraction = Attraction.objects.create(
            destination=existing_destination,
            name="Cubbon Park",
            category="nature",
            description="Existing attraction row",
        )
        coordinate_destination = Destination.objects.create(
            name="Chikkamagaluru", state="Legacy state", description="Existing hill destination", best_for="nature"
        )
        coordinate_attraction = Attraction.objects.create(
            destination=coordinate_destination,
            name="Hebbe Falls",
            category="nature",
            description="Existing attraction with a locally verified coordinate",
            latitude=12.345678,
            longitude=76.543210,
        )
        custom_destination = Destination.objects.create(
            name="User-added destination", state="Karnataka", description="Must not be removed", best_for="nature"
        )
        custom_attraction = Attraction.objects.create(
            destination=custom_destination,
            name="User-added attraction",
            category="nature",
            description="Must remain untouched by this seed batch",
        )

        self._run_seed_data()
        first_counts = (Destination.objects.count(), Attraction.objects.count())
        self._run_seed_data()

        self.assertEqual((Destination.objects.count(), Attraction.objects.count()), first_counts)
        self.assertEqual(Destination.objects.get(name="Bengaluru").pk, existing_destination.pk)
        self.assertEqual(Attraction.objects.get(destination=existing_destination, name="Cubbon Park").pk, existing_attraction.pk)
        coordinate_attraction.refresh_from_db()
        self.assertEqual(float(coordinate_attraction.latitude), 12.345678)
        self.assertEqual(float(coordinate_attraction.longitude), 76.543210)
        self.assertTrue(Destination.objects.filter(pk=custom_destination.pk).exists())
        self.assertTrue(Attraction.objects.filter(pk=custom_attraction.pk).exists())

    def test_new_attractions_have_correct_destinations_and_optional_coordinates(self):
        self._run_seed_data()
        from travel.management.commands.seed_data import ATTRACTION_COORDS

        self.assertTrue(all(isinstance(key, tuple) and len(key) == 2 for key in ATTRACTION_COORDS))

        expected_attraction_counts = {
            "Chikkamagaluru": 5,
            "Mangaluru": 5,
            "Udupi": 4,
            "Hampi": 4,
            "Badami": 3,
        }
        for destination_name, expected_count in expected_attraction_counts.items():
            destination = Destination.objects.get(name=destination_name, state="Karnataka")
            self.assertEqual(destination.attractions.count(), expected_count)

        hebbe_falls = Attraction.objects.get(
            destination__name="Chikkamagaluru", name="Hebbe Falls"
        )
        self.assertIsNone(hebbe_falls.latitude)
        self.assertIsNone(hebbe_falls.longitude)

        island = Attraction.objects.get(destination__name="Udupi", name="St Mary's Island")
        self.assertEqual(float(island.latitude), 13.377)
        self.assertEqual(float(island.longitude), 74.6749)

        virupaksha = Attraction.objects.get(destination__name="Hampi", name="Virupaksha Temple")
        self.assertEqual(float(virupaksha.latitude), 15.336667)
        self.assertEqual(float(virupaksha.longitude), 76.453333)


class AddVerifiedDestinationsCommandTests(TestCase):
    def _run_command(self, dry_run=False):
        from io import StringIO
        from django.core.management import call_command

        output = StringIO()
        call_command("add_verified_destinations", dry_run=dry_run, stdout=output)
        return output.getvalue()

    def test_dry_run_reports_plan_without_writing(self):
        output = self._run_command(dry_run=True)

        self.assertEqual(Destination.objects.count(), 0)
        self.assertEqual(Attraction.objects.count(), 0)
        self.assertIn("destinations_created=5", output)
        self.assertIn("attractions_created=21", output)
        self.assertIn("failed=0, dry_run=true", output)

    def test_creates_missing_rows_with_correct_associations_and_nullable_coordinates(self):
        output = self._run_command()

        self.assertEqual(Destination.objects.filter(state="Karnataka").count(), 5)
        self.assertEqual(Attraction.objects.count(), 21)
        self.assertIn("failed=0, dry_run=false", output)
        self.assertEqual(
            Attraction.objects.get(name="Hebbe Falls").destination.name,
            "Chikkamagaluru",
        )
        hebbe = Attraction.objects.get(name="Hebbe Falls")
        self.assertIsNone(hebbe.latitude)
        self.assertIsNone(hebbe.longitude)
        island = Attraction.objects.get(name="St Mary's Island")
        self.assertEqual(island.destination.name, "Udupi")
        self.assertEqual(float(island.latitude), 13.377)

    def test_is_idempotent_and_preserves_existing_and_unrelated_rows(self):
        existing_destination = Destination.objects.create(
            name="Chikkamagaluru", state="Karnataka", description="Keep this description", best_for="custom"
        )
        existing_attraction = Attraction.objects.create(
            destination=existing_destination,
            name="Mullayanagiri Peak",
            category="custom category",
            description="Keep this attraction",
            estimated_cost=777,
        )
        other_destination = Destination.objects.create(
            name="Local custom place", state="Karnataka", description="Unrelated", best_for="nature"
        )
        same_name_elsewhere = Attraction.objects.create(
            destination=other_destination, name="Panambur Beach", category="custom", description="Do not alter"
        )

        self._run_command()
        first_counts = (Destination.objects.count(), Attraction.objects.count())
        second_output = self._run_command()

        self.assertEqual((Destination.objects.count(), Attraction.objects.count()), first_counts)
        existing_destination.refresh_from_db()
        existing_attraction.refresh_from_db()
        same_name_elsewhere.refresh_from_db()
        self.assertEqual(existing_destination.description, "Keep this description")
        self.assertEqual(existing_attraction.description, "Keep this attraction")
        self.assertEqual(existing_attraction.estimated_cost, 777)
        self.assertEqual(same_name_elsewhere.description, "Do not alter")
        self.assertEqual(
            Attraction.objects.get(destination__name="Mangaluru", name="Panambur Beach").destination.name,
            "Mangaluru",
        )
        self.assertIn("destinations_created=0", second_output)
        self.assertIn("attractions_created=0", second_output)
        self.assertTrue(Destination.objects.filter(pk=other_destination.pk).exists())

    def test_write_failure_rolls_back_and_reports_failed_batch(self):
        from django.core.management.base import CommandError
        from unittest.mock import patch

        with patch(
            "travel.management.commands.add_verified_destinations.Attraction.objects.create",
            side_effect=RuntimeError("synthetic create failure"),
        ):
            with self.assertRaises(CommandError) as raised:
                self._run_command()

        self.assertIn("failed=1", str(raised.exception))
        self.assertEqual(Destination.objects.count(), 0)
        self.assertEqual(Attraction.objects.count(), 0)


