"""Resident API for the CivicSpeak Flutter app. Mounted at /api/."""
from django.urls import path

from . import api

app_name = "api"

urlpatterns = [
    path("meta/", api.meta, name="meta"),
    path("auth/register/", api.register, name="register"),
    path("auth/login/", api.login, name="login"),
    path("me/", api.me, name="me"),
    path("proposals/", api.proposals, name="proposals"),
    path("proposals/<int:pk>/", api.proposal_detail, name="proposal"),
    path("proposals/<int:pk>/follow/", api.follow, name="follow"),
    path("proposals/<int:pk>/feedback/", api.feedback, name="feedback"),
    path("proposals/<int:pk>/funding/", api.funding, name="funding"),
    path("map/", api.map_pins, name="map"),
    path("community/", api.community, name="community"),
    path("notifications/", api.notifications, name="notifications"),
    path("notifications/read/", api.notifications_read, name="notifications_read"),
    path("devices/", api.device_register, name="device_register"),
    path("devices/remove/", api.device_unregister, name="device_unregister"),
]
