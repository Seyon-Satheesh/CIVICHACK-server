"""Loads a few ILLUSTRATIVE proposals so the resident app has something to show.

    python manage.py load_demo_proposals          # add them (safe to run twice)
    python manage.py load_demo_proposals --remove # delete them again

Every proposal created here has is_illustrative=True, so residents see the "Illustrative" chip.
Run setup_civicspeak first.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.gis.geos import Point
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from server.models import (
    Category, CommunityPost, Impact, Municipality, Neighbourhood, Payer, ProjectAllocation, Proposal,
    ProposalPoint, ReserveFund, ReserveFundStatement, Source, StatusUpdate, TimelineStep,
)

SLUG_PREFIX = "demo-"

# Postal areas for the demo neighbourhoods, so text-message subscribers can be matched.
DEMO_FSAS = {"Annex": ["M5R", "M5S"], "Junction": ["M6N", "M6P"]}

DEMO = [
    {
        "slug": "demo-harbord-bike-lanes",
        "title": "Protected bike lanes on Harbord Street",
        "hood": "Annex",
        "cats": ["Transit", "Roads"],
        "status": "ongoing", "stage": "meeting",
        "summary": "The city wants to add protected bike lanes on both sides of Harbord Street between Ossington and Queen's Park. Parking would be removed on one side.",
        "affected": "People who live, park, cycle or run a business on Harbord Street.",
        "address": "Harbord St, Ossington Ave to Queen's Park",
        "point": (-79.4065, 43.6624), "radius": "0.8",
        "open": True, "deadline_days": 21,
        "cost": "2400000", "timing": "Construction summer 2027", "budget_line": "Cycling Network Plan",
        "changes": ["Curb-separated bike lanes on both sides", "Parking removed on the north side", "New loading zones for shops"],
        "pros": ["Safer trips for people cycling", "Fewer conflicts between bikes and cars"],
        "cons": ["About 60 parking spots removed", "Construction disruption for one summer"],
        "actions": ["Send a comment before the committee meeting", "Speak at the Infrastructure Committee (register in advance)"],
        "steps": [
            ("Staff report published", "staff", "done", -20, True, False),
            ("Public comment period", "public", "current", 0, True, True),
            ("Infrastructure Committee", "committee", "upcoming", 21, True, True),
            ("City Council vote", "council", "upcoming", 45, False, False),
        ],
        "payers": [("Cycling infrastructure reserve", "Transportation Reserve")],
        "allocation": ("1000000", "250000"),
    },
    {
        "slug": "demo-dundas-park-splash-pad",
        "title": "New splash pad in Dundas Park",
        "hood": "Junction",
        "cats": ["Parks"],
        "status": "completed", "stage": "decision",
        "summary": "Council approved and built a new splash pad and shade structure in Dundas Park after residents asked for more shade.",
        "affected": "Families who use Dundas Park.",
        "address": "Dundas Park",
        "point": (-79.4703, 43.6655), "radius": "0.5",
        "open": False,
        "cost": "850000", "timing": "Opened June 2026", "budget_line": "Parks capital budget",
        "changes": ["Splash pad with accessible surface", "Two new shade structures", "Water fountain"],
        "pros": [], "cons": [],
        "actions": [],
        "steps": [
            ("Community meeting", "public", "done", -400, True, True),
            ("Council approval", "council", "done", -300, True, False),
            ("Construction", "city", "done", -120, True, False),
        ],
        "payers": [("Parkland acquisition reserve", "Parks Reserve")],
        "allocation": ("850000", "820000"),
        "update": ("Splash pad is open", "The splash pad opened for the summer with the extra shade residents asked for."),
        "impacts": [("positive", "Park visits on hot days roughly doubled, according to staff counts."),
                    ("neutral", "Water use is being monitored by the city.")],
        "post": {
            "title": "Dundas Park got the shade you asked for",
            "did": ["Residents filled out the survey and came to the community meeting", "Many comments asked for more shade near the play area"],
            "changed": ["Staff added a second shade structure to the design", "The splash pad surface was changed to be accessible"],
            "thanks": "Thank you to everyone who shared their ideas.",
        },
    },
    {
        "slug": "demo-bloor-parking-garage",
        "title": "Municipal parking garage on Bloor Street",
        "hood": "Annex",
        "cats": ["Roads"],
        "status": "abandoned", "stage": "decision",
        "summary": "A plan for a city parking garage was withdrawn after the cost estimate rose and staff recommended other options.",
        "affected": "Drivers and businesses on Bloor Street.",
        "address": "Bloor St W",
        "point": (-79.4110, 43.6655), "radius": "0.4",
        "open": False,
        "cost": "18000000", "timing": "Not going ahead", "budget_line": "Parking Authority",
        "changes": ["No garage will be built"],
        "pros": [], "cons": [],
        "actions": [],
        "steps": [
            ("Feasibility study", "staff", "done", -200, True, False),
            ("Committee decision to withdraw", "committee", "done", -60, True, False),
        ],
        "payers": [("Parking Authority", None)],
        "update": ("Plan withdrawn", "The committee voted not to go ahead because the estimate rose by 40% and street parking changes were cheaper."),
    },
]


class Command(BaseCommand):
    help = "Loads (or removes) illustrative demo proposals for the resident app."

    def add_arguments(self, parser):
        parser.add_argument("--remove", action="store_true")

    @transaction.atomic
    def handle(self, *args, **opts):
        muni = Municipality.objects.order_by("pk").first()
        if not muni:
            raise CommandError("Run `python manage.py setup_civicspeak` first.")
        if opts["remove"]:
            n, _ = Proposal.objects.filter(municipality=muni, slug__startswith=SLUG_PREFIX).delete()
            self.stdout.write(self.style.SUCCESS(f"Removed demo content ({n} rows)."))
            return

        today = date.today()
        src = Source.objects.get_or_create(
            municipality=muni, kind=Source.Kind.OTHER, title="Illustrative example (not a real city record)",
            defaults={"url": muni.official_participation_url or "https://www.toronto.ca/"},
        )[0]
        for d in DEMO:
            if Proposal.objects.filter(municipality=muni, slug=d["slug"]).exists():
                continue
            hood, _ = Neighbourhood.objects.get_or_create(municipality=muni, name=d["hood"])
            if not hood.postal_fsas and d["hood"] in DEMO_FSAS:
                hood.postal_fsas = DEMO_FSAS[d["hood"]]
                hood.save(update_fields=["postal_fsas"])
            p = Proposal.objects.create(
                municipality=muni, neighbourhood=hood, slug=d["slug"], title=d["title"], summary=d["summary"],
                affected=d["affected"], address=d["address"], location=Point(*d["point"], srid=4326),
                impact_radius_km=Decimal(d["radius"]), status=d["status"], stage=d["stage"],
                is_illustrative=True, is_published=True, published_at=timezone.now(),
                participation_open=d["open"],
                participation_url=(muni.official_participation_url or "https://www.toronto.ca/") if d["open"] else "",
                participation_deadline=timezone.now() + timedelta(days=d["deadline_days"]) if d.get("deadline_days") else None,
                deadline_source=src if d.get("deadline_days") else None,
                cost_estimate=Decimal(d["cost"]), cost_note="Illustrative figure", expected_timing=d["timing"],
                budget_line=d["budget_line"],
            )
            p.sources.add(src)
            for name in d["cats"]:
                cat = Category.objects.filter(name__iexact=name).first()
                if cat:
                    p.categories.add(cat)
            for kind in ("changes", "pros", "cons", "actions"):
                for i, text in enumerate(d[kind]):
                    ProposalPoint.objects.create(proposal=p, kind={"changes": "change", "pros": "pro", "cons": "con", "actions": "action"}[kind], text=text, order=i)
            for i, (label, level, state, days, confirmed, can) in enumerate(d["steps"]):
                TimelineStep.objects.create(proposal=p, order=i, label=label, level=level, state=state,
                                            date=today + timedelta(days=days), date_confirmed=confirmed,
                                            residents_can_participate=can, source=src)
            fund = None
            for payer, fund_name in d["payers"]:
                if fund_name:
                    fund, _ = ReserveFund.objects.get_or_create(municipality=muni, name=fund_name)
                Payer.objects.create(proposal=p, name=payer, reserve_fund=fund if fund_name else None)
            if fund and d.get("allocation"):
                st, _ = ReserveFundStatement.objects.get_or_create(
                    fund=fund, year=today.year - 1,
                    defaults={"opening_balance": Decimal("12000000"), "collected": Decimal("4000000"), "interest": Decimal("300000"),
                              "draws": Decimal("3500000"), "closing_balance": Decimal("12800000"), "source": src},
                )
                ProjectAllocation.objects.create(proposal=p, statement=st, allocated=Decimal(d["allocation"][0]), spent=Decimal(d["allocation"][1]))
            if d.get("update"):
                StatusUpdate.objects.create(proposal=p, title=d["update"][0], summary=d["update"][1])
            for kind, text in d.get("impacts", []):
                Impact.objects.create(proposal=p, kind=kind, text=text, observed_on=today - timedelta(days=30), source=src)
            if d.get("post"):
                post = d["post"]
                CommunityPost.objects.create(proposal=p, title=post["title"], community_did=post["did"],
                                             what_changed=post["changed"], thanks=post["thanks"], published_at=timezone.now())
        self.stdout.write(self.style.SUCCESS("Demo proposals loaded (all marked Illustrative)."))
