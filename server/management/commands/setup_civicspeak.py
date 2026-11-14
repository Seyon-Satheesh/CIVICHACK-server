"""Creates the starting data CivicSpeak needs. Safe to run on every deploy (it never duplicates).

    python manage.py setup_civicspeak

Environment variables (all optional):
    MUNICIPALITY_NAME   default "Toronto"
    MUNICIPALITY_PROVINCE default "ON"
    ADMIN_USERNAME / ADMIN_PASSWORD / ADMIN_EMAIL
        If set, creates that account (superuser + Editor) the first time.
"""
import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from server.models import Category, Municipality, StaffMembership, Topic

TOPICS = [
    ("planning", "Urban Planning & Growth"),
    ("roads", "Roads, Transit & Traffic"),
    ("parks", "Parks, Recreation & Culture"),
    ("bylaws", "Neighbourhood Rules & Bylaws"),
    ("budget", "City Budgets & Taxes"),
    ("safety", "Emergency & Safety Services"),
    ("water", "Water, Waste & Utilities"),
    ("community", "Community & Social Services"),
]

CATEGORIES = {
    "Zoning": "planning", "Housing": "planning", "Renting": "planning", "Home Ownership": "planning",
    "Roads": "roads", "Transit": "roads", "Parking": "roads",
    "Parks": "parks", "Recreation": "parks", "Culture": "parks", "Events": "parks",
    "Bylaws": "bylaws", "Legal Procedures": "bylaws",
    "Budget": "budget", "Taxation": "budget",
    "Safety": "safety", "Crime": "safety",
    "Water": "water", "Sewage": "water", "Waste Disposal": "water", "Electric": "water",
    "Education": "community", "Social Support": "community", "Homelessness": "community",
    "Food Insecurity": "community", "2SLGBTQIA+ Rights": "community", "Women's Rights": "community",
    "Other": "community",
}

OFFICIAL_LINKS = {
    ("Toronto", "ON"): "https://www.toronto.ca/city-government/council/council-committee-meetings/have-your-say/",
}


class Command(BaseCommand):
    help = "Create topics, categories, the municipality and (optionally) the first staff account."

    @transaction.atomic
    def handle(self, *args, **options):
        topics = {}
        for key, label in TOPICS:
            topics[key], _ = Topic.objects.update_or_create(key=key, defaults={"label": label})
        for name, key in CATEGORIES.items():
            Category.objects.update_or_create(name=name, defaults={"topic": topics[key]})

        name = os.environ.get("MUNICIPALITY_NAME", "Toronto")
        prov = os.environ.get("MUNICIPALITY_PROVINCE", "ON")
        muni, created = Municipality.objects.get_or_create(
            name=name, province=prov,
            defaults={"languages": ["en", "fr"], "official_participation_url": OFFICIAL_LINKS.get((name, prov), "")},
        )
        self.stdout.write(f"Municipality: {muni} ({'created' if created else 'exists'})")

        username, password = os.environ.get("ADMIN_USERNAME"), os.environ.get("ADMIN_PASSWORD")
        if username and password:
            User = get_user_model()
            user, made = User.objects.get_or_create(
                username=username, defaults={"email": os.environ.get("ADMIN_EMAIL", ""), "is_staff": True, "is_superuser": True})
            if made:
                user.set_password(password)
                user.save()
            StaffMembership.objects.get_or_create(user=user, defaults={"municipality": muni, "role": StaffMembership.Role.EDITOR})
            self.stdout.write(f"Staff account: {username} ({'created' if made else 'exists'})")
        self.stdout.write(self.style.SUCCESS("CivicSpeak setup complete."))
