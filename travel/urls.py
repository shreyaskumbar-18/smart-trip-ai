from django.urls import path
from . import views


urlpatterns = [

    # =========================
    # HOME
    # =========================
    path(
        "",
        views.home,
        name="home",
    ),

    # =========================
    # AUTHENTICATION
    # =========================
    path(
        "register/",
        views.register_view,
        name="register",
    ),
    path(
        "login/",
        views.login_view,
        name="login",
    ),
    path(
        "logout/",
        views.logout_view,
        name="logout",
    ),

    # =========================
    # DASHBOARD / PROFILE
    # =========================
    path(
        "dashboard/",
        views.dashboard,
        name="dashboard",
    ),
    path(
        "profile/",
        views.profile,
        name="profile",
    ),

    # =========================
    # DESTINATIONS
    # =========================
    path(
        "destinations/",
        views.destinations,
        name="destinations",
    ),
    path(
        "destinations/<int:pk>/",
        views.destination_detail,
        name="destination_detail",
    ),

    # =========================
    # TRIP PLANNER
    # =========================
    path(
        "trip-planner/",
        views.trip_planner,
        name="trip_planner",
    ),

    # =========================
    # TRIP DETAILS
    # =========================
    path(
        "trips/<int:pk>/",
        views.trip_detail,
        name="trip_detail",
    ),

    # =========================
    # SAVE TRIP
    # =========================
    path(
        "trips/<int:pk>/save/",
        views.save_trip,
        name="save_trip",
    ),

    # =========================
    # DELETE TRIP
    # =========================
    path(
        "trips/<int:pk>/delete/",
        views.delete_trip,
        name="delete_trip",
    ),

    # =========================
    # FEEDBACK
    # =========================
    path(
        "trips/<int:pk>/feedback/<int:item_id>/<str:action>/",
        views.feedback,
        name="feedback",
    ),

    # =========================
    # BUDGET
    # =========================
    path(
        "trips/<int:pk>/budget/",
        views.budget,
        name="budget",
    ),

    # =========================
    # SAVED TRIPS
    # =========================
    path(
        "saved-trips/",
        views.saved_trips,
        name="saved_trips",
    ),
    path(
        "saved-trips/<int:pk>/remove/",
        views.remove_saved_trip,
        name="remove_saved_trip",
    ),

    # =========================
    # RECOMMENDATIONS
    # =========================
    path(
        "recommendations/",
        views.recommendations,
        name="recommendations",
    ),

    # =========================
    # WHAT-IF PLANNER
    # =========================
    path(
        "trips/<int:pk>/what-if/",
        views.what_if_view,
        name="what_if",
    ),

    # =========================
    # DYNAMIC REPLANNING
    # =========================
    path(
        "trips/<int:pk>/replan/",
        views.replan,
        name="replan",
    ),

    # =========================
    # GROUP TRAVEL
    # =========================
    path(
        "trips/<int:pk>/group/",
        views.group_trip,
        name="group",
    ),

    # =========================
    # AI TRAVEL ASSISTANT
    # =========================
    path(
        "trips/<int:pk>/assistant/",
        views.assistant,
        name="assistant",
    ),
]