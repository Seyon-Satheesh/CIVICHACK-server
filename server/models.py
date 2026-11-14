# from django.db import models

# # Create your models here.

"""
CivicSpeak – Django data models for PostgreSQL (with the PostGIS extension).

Maps the demo's browser store (js/store.js, js/data.js) to a real database.
Requires: django.contrib.gis and django.contrib.postgres in INSTALLED_APPS,
and `CREATE EXTENSION postgis;` on the database.

Design notes
- Multi-municipality from day one (Municipality), so other cities can adopt it.
- Staff vs residents: Django's built-in User; staff permissions via Groups
  ("Municipal staff", "Community post editors").
- Privacy: only the first 3 characters of a postal code (FSA) are stored;
  kiosk feedback can be anonymous (user is null).
- Vote totals are never exposed to residents; that is enforced in the API/views,
  not here, but Feedback is the only place opinions are stored.
"""
from django.conf import settings
from django.contrib.gis.db import models as gis
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator, MinValueValidator
from django.db import models
from django.db.models import Q


class TimeStamped(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# ---------------------------------------------------------------- place

class Municipality(TimeStamped):
    name = models.CharField(max_length=120)
    province = models.CharField(max_length=2)                 # "ON", "QC", ...
    languages = ArrayField(models.CharField(max_length=8), default=list)  # ["en", "fr"]
    official_participation_url = models.URLField(blank=True)  # e.g. "Have your say" page
    boundary = gis.MultiPolygonField(srid=4326, null=True, blank=True)

    class Meta:
        verbose_name_plural = "municipalities"
        constraints = [models.UniqueConstraint(fields=["name", "province"], name="uniq_municipality")]

    def __str__(self):
        return f"{self.name}, {self.province}"


class Neighbourhood(models.Model):
    municipality = models.ForeignKey(Municipality, on_delete=models.CASCADE, related_name="neighbourhoods")
    name = models.CharField(max_length=120)
    ward = models.CharField(max_length=40, blank=True)
    boundary = gis.MultiPolygonField(srid=4326, null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["municipality", "name"], name="uniq_neighbourhood")]

    def __str__(self):
        return self.name


class StaffMembership(TimeStamped):
    """Which municipality a staff account works for. Admin views only show that municipality's data."""
    class Role(models.TextChoices):
        EDITOR = "editor", "Editor (publish proposals and posts)"
        MODERATOR = "moderator", "Moderator (feedback only)"
        VIEWER = "viewer", "Viewer"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="staff")
    municipality = models.ForeignKey(Municipality, on_delete=models.CASCADE, related_name="staff")
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.EDITOR)


# ---------------------------------------------------------------- topics (drive personalization)

class Topic(models.Model):
    """Survey interests (planning, roads, parks, budget, ...). Categories map to a topic."""
    key = models.SlugField(unique=True)          # "roads"
    label = models.CharField(max_length=80)      # "Roads, Transit & Traffic"

    def __str__(self):
        return self.label


class Category(models.Model):
    name = models.CharField(max_length=60, unique=True)  # "Zoning", "Transit", "Water"...
    topic = models.ForeignKey(Topic, on_delete=models.PROTECT, related_name="categories")

    class Meta:
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


# ---------------------------------------------------------------- sources (every fact links somewhere)

class Source(TimeStamped):
    class Kind(models.TextChoices):
        STAFF_REPORT = "staff_report", "Staff report"
        COMMITTEE = "committee", "Committee decision"
        COUNCIL = "council", "Council decision"
        APPLICATION = "application", "Development application"
        NOTICE = "notice", "Public notice"
        FINANCIAL = "financial", "Financial statement"
        OPEN_DATA = "open_data", "Open data"
        OTHER = "other", "Other"

    municipality = models.ForeignKey(Municipality, on_delete=models.CASCADE, related_name="sources")
    kind = models.CharField(max_length=20, choices=Kind.choices)
    title = models.CharField(max_length=300)
    url = models.URLField(max_length=500)
    published_on = models.DateField(null=True, blank=True)
    agenda_item = models.CharField(max_length=40, blank=True)   # e.g. council item number

    def __str__(self):
        return self.title


# ---------------------------------------------------------------- proposals

class Proposal(TimeStamped):
    class Status(models.TextChoices):
        ONGOING = "ongoing", "Ongoing"
        COMPLETED = "completed", "Completed"
        ABANDONED = "abandoned", "Abandoned"

    class Stage(models.TextChoices):
        NOTICE = "notice", "Notice"
        MEETING = "meeting", "Meeting"
        DECISION = "decision", "Decision"
        APPEAL = "appeal", "Appeal"

    municipality = models.ForeignKey(Municipality, on_delete=models.CASCADE, related_name="proposals")
    neighbourhood = models.ForeignKey(Neighbourhood, on_delete=models.SET_NULL, null=True, blank=True,
                                      related_name="proposals")          # null = city-wide
    slug = models.SlugField(max_length=80)
    title = models.CharField(max_length=200)
    summary = models.TextField()                                         # plain-language summary
    affected = models.TextField(blank=True)                              # who is affected
    address = models.CharField(max_length=200, blank=True)
    location = gis.PointField(srid=4326, null=True, blank=True)          # pin on the map
    impact_radius_km = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True,
                                           validators=[MinValueValidator(0)])
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ONGOING, db_index=True)
    stage = models.CharField(max_length=10, choices=Stage.choices, default=Stage.NOTICE)
    categories = models.ManyToManyField(Category, related_name="proposals")
    sources = models.ManyToManyField(Source, related_name="proposals", blank=True)

    is_illustrative = models.BooleanField(default=False)                 # demo content flag
    is_published = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True,
                                   related_name="proposals_created")

    # participation (the "What you can do" section)
    participation_open = models.BooleanField(default=False)
    participation_url = models.URLField(max_length=500, blank=True)
    participation_deadline = models.DateTimeField(null=True, blank=True)  # only if officially published
    deadline_source = models.ForeignKey(Source, on_delete=models.SET_NULL, null=True, blank=True,
                                        related_name="+")

    # cost and who pays
    cost_estimate = models.DecimalField(max_digits=14, decimal_places=2, null=True, blank=True)
    cost_note = models.CharField(max_length=200, blank=True)             # "As stated in staff report"
    expected_timing = models.CharField(max_length=120, blank=True)       # "Spring 2027"
    budget_line = models.CharField(max_length=120, blank=True)

    search = SearchVectorField(null=True)                                # full-text search (title + summary)

    class Meta:
        ordering = ["-published_at"]
        constraints = [
            models.UniqueConstraint(fields=["municipality", "slug"], name="uniq_proposal_slug"),
            # Only ongoing proposals can be open for input.
            models.CheckConstraint(condition=Q(participation_open=False) | Q(status="ongoing"),
                                   name="participation_only_when_ongoing"),
            models.CheckConstraint(condition=Q(participation_open=False) | ~Q(participation_url=""),
                                   name="open_needs_official_link"),
        ]
        indexes = [
            models.Index(fields=["municipality", "status"]),
            GinIndex(fields=["search"]),
        ]

    def __str__(self):
        return self.title


class ProposalPoint(models.Model):
    """Ordered bullet points: what's changing, pros, cons, and actions residents can take."""
    class Kind(models.TextChoices):
        CHANGE = "change", "What's changing"
        PRO = "pro", "Pro"
        CON = "con", "Con"
        ACTION = "action", "What you can do"

    proposal = models.ForeignKey(Proposal, on_delete=models.CASCADE, related_name="points")
    kind = models.CharField(max_length=6, choices=Kind.choices)
    text = models.CharField(max_length=400)
    order = models.PositiveSmallIntegerField(default=0)
    source = models.ForeignKey(Source, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ["kind", "order"]
        indexes = [models.Index(fields=["proposal", "kind"])]


class TimelineStep(models.Model):
    """The Process tab. Keeps staff, committee and council steps separate."""
    class Level(models.TextChoices):
        APPLICANT = "applicant", "Applicant"
        STAFF = "staff", "Staff"
        PUBLIC = "public", "Public"
        COMMITTEE = "committee", "Committee"
        COUNCIL = "council", "Council"
        TRIBUNAL = "tribunal", "Tribunal"
        CITY = "city", "City operations"

    class State(models.TextChoices):
        DONE = "done", "Done"
        CURRENT = "current", "Happening now"
        UPCOMING = "upcoming", "Next"
        UNKNOWN = "unknown", "Date not set"

    proposal = models.ForeignKey(Proposal, on_delete=models.CASCADE, related_name="steps")
    order = models.PositiveSmallIntegerField()
    label = models.CharField(max_length=120)
    level = models.CharField(max_length=10, choices=Level.choices)
    state = models.CharField(max_length=10, choices=State.choices)
    date = models.DateField(null=True, blank=True)
    date_confirmed = models.BooleanField(default=False)          # a meeting date is not a deadline
    note = models.CharField(max_length=300, blank=True)
    residents_can_participate = models.BooleanField(default=False)
    source = models.ForeignKey(Source, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ["order"]
        constraints = [models.UniqueConstraint(fields=["proposal", "order"], name="uniq_step_order")]


class Payer(models.Model):
    """Who pays: capital budget, development charges, water rates, developer..."""
    proposal = models.ForeignKey(Proposal, on_delete=models.CASCADE, related_name="payers")
    name = models.CharField(max_length=120)
    reserve_fund = models.ForeignKey("ReserveFund", on_delete=models.SET_NULL, null=True, blank=True)


class StatusUpdate(TimeStamped):
    """Updates woven into the Breakdown summary as they happen."""
    class Importance(models.TextChoices):
        URGENT = "urgent", "Urgent"
        HIGH = "high", "High"
        ESSENTIAL = "essential", "Essential"
        NON_ESSENTIAL = "non_essential", "Non-essential"

    proposal = models.ForeignKey(Proposal, on_delete=models.CASCADE, related_name="updates")
    title = models.CharField(max_length=160)
    summary = models.TextField()
    importance = models.CharField(max_length=14, choices=Importance.choices, default=Importance.ESSENTIAL)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)

    class Meta:
        ordering = ["-created_at"]


class Impact(TimeStamped):
    """Impacts tab for completed proposals: positive, neutral or negative effects since completion."""
    class Kind(models.TextChoices):
        POSITIVE = "positive", "Positive"
        NEUTRAL = "neutral", "Neutral"
        NEGATIVE = "negative", "Negative"

    proposal = models.ForeignKey(Proposal, on_delete=models.CASCADE, related_name="impacts")
    kind = models.CharField(max_length=8, choices=Kind.choices)
    text = models.CharField(max_length=400)
    observed_on = models.DateField()
    source = models.ForeignKey(Source, on_delete=models.SET_NULL, null=True, blank=True)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)

    class Meta:
        ordering = ["-observed_on"]


# ---------------------------------------------------------------- follow the money

class ReserveFund(models.Model):
    """e.g. Development Charges – Roads, Parks, Transit, Water."""
    municipality = models.ForeignKey(Municipality, on_delete=models.CASCADE, related_name="reserve_funds")
    name = models.CharField(max_length=120)
    service = models.CharField(max_length=60, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["municipality", "name"], name="uniq_reserve_fund")]


class ReserveFundStatement(models.Model):
    """Annual figures from the city's published statement (amounts in dollars)."""
    fund = models.ForeignKey(ReserveFund, on_delete=models.CASCADE, related_name="statements")
    year = models.PositiveSmallIntegerField()
    opening_balance = models.DecimalField(max_digits=16, decimal_places=2)
    collected = models.DecimalField(max_digits=16, decimal_places=2)
    interest = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    draws = models.DecimalField(max_digits=16, decimal_places=2)           # spent on projects
    closing_balance = models.DecimalField(max_digits=16, decimal_places=2)
    source = models.ForeignKey(Source, on_delete=models.PROTECT)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["fund", "year"], name="uniq_statement_year")]


class ProjectAllocation(models.Model):
    """Links a statement line to a proposal: is money actually flowing to it?"""
    proposal = models.ForeignKey(Proposal, on_delete=models.CASCADE, related_name="allocations")
    statement = models.ForeignKey(ReserveFundStatement, on_delete=models.CASCADE, related_name="allocations")
    allocated = models.DecimalField(max_digits=14, decimal_places=2)
    spent = models.DecimalField(max_digits=14, decimal_places=2, default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["proposal", "statement"], name="uniq_allocation"),
            models.CheckConstraint(condition=Q(spent__lte=models.F("allocated")), name="spent_lte_allocated"),
        ]


# ---------------------------------------------------------------- residents

postal_fsa = RegexValidator(r"^[A-Z]\d[A-Z]$", "Use the first 3 characters of a postal code, e.g. N2L.")


class ResidentProfile(TimeStamped):
    """Created after the onboarding survey. Contact details stay on User (email) or here (phone)."""
    class Area(models.TextChoices):
        CITY = "city", "Whole city"
        NEIGHBOURHOOD = "neighbourhood", "My neighbourhood"

    class Trigger(models.TextChoices):
        OPEN_ONLY = "open", "Only when input is open"
        EVERY = "every", "Every agenda appearance, including results"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="resident")
    municipality = models.ForeignKey(Municipality, on_delete=models.PROTECT)
    area_type = models.CharField(max_length=14, choices=Area.choices)
    neighbourhood = models.ForeignKey(Neighbourhood, on_delete=models.SET_NULL, null=True, blank=True)
    postal_fsa = models.CharField(max_length=3, blank=True, validators=[postal_fsa])

    interests = models.ManyToManyField(Topic, related_name="interested_residents", blank=True)
    notify_trigger = models.CharField(max_length=5, choices=Trigger.choices, default=Trigger.OPEN_ONLY)
    notify_channels = ArrayField(models.CharField(max_length=8), default=list)   # ["app","email","sms"]
    phone = models.CharField(max_length=20, blank=True)                           # only if SMS chosen

    language = models.CharField(max_length=8, default="en")
    audio_mode = models.BooleanField(default=False)
    large_text = models.BooleanField(default=False)
    joined_via_kiosk = models.ForeignKey("Kiosk", on_delete=models.SET_NULL, null=True, blank=True)

    following = models.ManyToManyField(Proposal, through="Follow", related_name="followers")

    def clean(self):
        if self.area_type == self.Area.NEIGHBOURHOOD and not self.neighbourhood:
            raise ValidationError("Choose a neighbourhood.")
        if "sms" in self.notify_channels and not self.phone:
            raise ValidationError("A mobile number is needed for text alerts.")


class SurveyResponse(TimeStamped):
    """Raw onboarding answers, versioned so the survey can change without losing history."""
    resident = models.ForeignKey(ResidentProfile, on_delete=models.CASCADE, related_name="survey_responses")
    survey_version = models.PositiveSmallIntegerField(default=1)
    answers = models.JSONField()     # {"q1": [...], "q2": [...], "q3": [...], "q4": [...], "q4other": "..."}

    class Meta:
        indexes = [GinIndex(fields=["answers"])]


class Follow(TimeStamped):
    """+ button: pins the proposal on the resident's map and drives notifications."""
    resident = models.ForeignKey(ResidentProfile, on_delete=models.CASCADE)
    proposal = models.ForeignKey(Proposal, on_delete=models.CASCADE)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["resident", "proposal"], name="uniq_follow")]


# ---------------------------------------------------------------- kiosks and feedback

class Kiosk(TimeStamped):
    municipality = models.ForeignKey(Municipality, on_delete=models.CASCADE, related_name="kiosks")
    site_name = models.CharField(max_length=120)               # "Hillcrest Community Centre"
    neighbourhood = models.ForeignKey(Neighbourhood, on_delete=models.SET_NULL, null=True)
    location = gis.PointField(srid=4326, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    idle_reset_seconds = models.PositiveSmallIntegerField(default=90)


class Feedback(TimeStamped):
    """Support / Neutral / Oppose plus an optional comment. Totals are staff-only."""
    class Choice(models.TextChoices):
        SUPPORT = "support", "Support"
        NEUTRAL = "neutral", "Neutral"
        OPPOSE = "oppose", "Oppose"

    class Channel(models.TextChoices):
        APP = "app", "App"
        KIOSK = "kiosk", "Kiosk"

    proposal = models.ForeignKey(Proposal, on_delete=models.CASCADE, related_name="feedback")
    resident = models.ForeignKey(ResidentProfile, on_delete=models.SET_NULL, null=True, blank=True)  # null = anonymous
    kiosk = models.ForeignKey(Kiosk, on_delete=models.SET_NULL, null=True, blank=True)
    channel = models.CharField(max_length=5, choices=Channel.choices, default=Channel.APP)
    choice = models.CharField(max_length=7, choices=Choice.choices)
    comment = models.CharField(max_length=500, blank=True)
    marked_helpful = models.BooleanField(default=False)
    used_in_decision = models.BooleanField(default=False)
    is_hidden = models.BooleanField(default=False)            # moderation

    class Meta:
        constraints = [
            # One response per resident per proposal (they can update it). Anonymous kiosk rows are exempt.
            models.UniqueConstraint(fields=["resident", "proposal"], condition=Q(resident__isnull=False),
                                    name="one_feedback_per_resident"),
            models.CheckConstraint(condition=Q(channel="kiosk") | Q(kiosk__isnull=True), name="kiosk_only_on_kiosk_channel"),
        ]
        indexes = [models.Index(fields=["proposal", "choice"])]


# ---------------------------------------------------------------- community and notifications

class CommunityPost(TimeStamped):
    """One story per completed proposal: what residents did and what changed because of it."""
    proposal = models.OneToOneField(Proposal, on_delete=models.CASCADE, related_name="community_post")
    title = models.CharField(max_length=200)
    community_did = ArrayField(models.CharField(max_length=300))
    what_changed = ArrayField(models.CharField(max_length=300))
    thanks = models.CharField(max_length=300, blank=True)
    highlighted_feedback = models.ManyToManyField(Feedback, blank=True, related_name="featured_in")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    published_at = models.DateTimeField(null=True, blank=True)

    def clean(self):
        if self.proposal.status != Proposal.Status.COMPLETED:
            raise ValidationError("Community posts are only for completed proposals.")


class Notification(models.Model):
    """Bell feed. Created by a background job when updates, impacts or posts are published,
    filtered by each resident's interests, area, follows and notify_trigger, so nobody is spammed."""
    class Kind(models.TextChoices):
        UPDATE = "update", "Update on a followed proposal"
        IMPACT = "impact", "New impact"
        COMMUNITY = "community", "Community story"
        OPEN = "open", "Input is open near you"

    resident = models.ForeignKey(ResidentProfile, on_delete=models.CASCADE, related_name="notifications")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    proposal = models.ForeignKey(Proposal, on_delete=models.CASCADE, null=True, blank=True)
    update = models.ForeignKey(StatusUpdate, on_delete=models.CASCADE, null=True, blank=True)
    impact = models.ForeignKey(Impact, on_delete=models.CASCADE, null=True, blank=True)
    post = models.ForeignKey(CommunityPost, on_delete=models.CASCADE, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)
    sent_email_at = models.DateTimeField(null=True, blank=True)
    sent_sms_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["resident", "read_at"])]
        constraints = [
            # Never notify the same resident twice about the same thing.
            models.UniqueConstraint(fields=["resident", "kind", "update"], condition=Q(update__isnull=False), name="uniq_notif_update"),
            models.UniqueConstraint(fields=["resident", "kind", "impact"], condition=Q(impact__isnull=False), name="uniq_notif_impact"),
            models.UniqueConstraint(fields=["resident", "kind", "post"], condition=Q(post__isnull=False), name="uniq_notif_post"),
        ]
