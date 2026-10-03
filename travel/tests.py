from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase

from .models import Destination, Trip
from .services.feasibility import what_if
from .services.weather import demo_forecast


class SmartTripServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser",
            password="testpass123",
        )
        self.destination = Destination.objects.create(
            name="Test City",
            state="Test State",
            description="Test destination",
            average_daily_cost=2000,
            best_for="culture,nature",
        )

    def test_trip_days_are_inclusive(self):
        trip = Trip.objects.create(
            user=self.user,
            destination=self.destination,
            title="Test Trip",
            start_date=date(2026, 10, 2),
            end_date=date(2026, 10, 5),
            travelers=2,
            budget=20000,
        )
        self.assertEqual(trip.days, 4)

    def test_weather_demo_is_deterministic(self):
        condition, advice = demo_forecast(3)
        self.assertEqual(condition, "Rain")
        self.assertIn("indoor", advice.lower())

    def test_what_if_changes_budget_and_days(self):
        trip = Trip.objects.create(
            user=self.user,
            destination=self.destination,
            title="Test Trip",
            start_date=date(2026, 10, 2),
            end_date=date(2026, 10, 3),
            travelers=2,
            budget=10000,
        )
        result = what_if(
            trip,
            budget_change=5000,
            extra_days=1,
        )
        self.assertEqual(result["budget"], 15000)
        self.assertEqual(result["days"], 3)
        self.assertEqual(result["estimated"], 12000)
