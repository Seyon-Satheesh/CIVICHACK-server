"""Push notifications to the CivicSpeak Flutter app (Firebase Cloud Messaging).

Sent when staff publish a proposal, change it, or post an update or impact in the admin console.
Who gets one: residents who chose "app" notifications and either
  - follow the proposal, or
  - match it: one of their topics AND their area (whole city, their neighbourhood, their postal area,
    or the proposal's pin falls inside their neighbourhood's boundary) AND their timing choice
    ("every" update, or "open" = only while residents can have a say).
Each push is also saved as a Notification, so it shows under the bell in the app.

Settings come from environment variables (see backend/settings.py):
  FIREBASE_CREDENTIALS_JSON (service-account JSON, raw or base64) or FIREBASE_CREDENTIALS_FILE (path),
  PUSH_ALERTS_ENABLED, ALERT_COOLDOWN_HOURS.
If Firebase isn't configured, notifications still appear in the app's bell; only the push is skipped.
"""
import base64
import json
import logging
import threading
from datetime import timedelta

from django.conf import settings
from django.db import close_old_connections, transaction
from django.db.models import Q
from django.utils import timezone

from .models import DeviceToken, Notification, Proposal, ResidentProfile

log = logging.getLogger(__name__)

_app = None
_app_lock = threading.Lock()


# ---------------------------------------------------------------- Firebase

def _firebase():
    """Returns the Firebase app, or None if no credentials are set."""
    global _app
    if _app is not None:
        return _app
    raw, path = settings.FIREBASE_CREDENTIALS_JSON, settings.FIREBASE_CREDENTIALS_FILE
    if not (raw or path):
        return None
    with _app_lock:
        if _app is None:
            import firebase_admin
            from firebase_admin import credentials
            if raw:
                text = raw.strip()
                if not text.startswith("{"):          # allow base64 so it fits in one env variable
                    text = base64.b64decode(text).decode()
                cred = credentials.Certificate(json.loads(text))
            else:
                cred = credentials.Certificate(path)
            _app = firebase_admin.initialize_app(cred, name="civicspeak")
    return _app


def send_push(tokens, title, body, data):
    """Sends to many devices (500 per batch). Turns off tokens Firebase reports as invalid. Returns the number sent."""
    app = _firebase()
    if app is None:
        log.info("Push not sent (Firebase not configured): %s", title)
        return 0
    from firebase_admin import messaging
    sent = 0
    for i in range(0, len(tokens), 500):
        batch = tokens[i:i + 500]
        message = messaging.MulticastMessage(
            tokens=batch,
            notification=messaging.Notification(title=title, body=body),
            data={k: str(v) for k, v in data.items()},
            android=messaging.AndroidConfig(priority="high"),
            apns=messaging.APNSConfig(payload=messaging.APNSPayload(aps=messaging.Aps(sound="default"))),
        )
        try:
            resp = messaging.send_each_for_multicast(message, app=app)
        except Exception:
            log.exception("Push batch failed")
            continue
        sent += resp.success_count
        dead = [tok for tok, r in zip(batch, resp.responses)
                if not r.success and isinstance(r.exception, (messaging.UnregisteredError, messaging.SenderIdMismatchError))]
        if dead:
            DeviceToken.objects.filter(token__in=dead).update(is_active=False)
    return sent


# ---------------------------------------------------------------- who matches

def residents_for(proposal):
    """Residents with app notifications on who follow the proposal or match its topics, area and timing."""
    p = proposal
    base = ResidentProfile.objects.filter(municipality=p.municipality, user__is_active=True,
                                          notify_channels__contains=["app"])

    prefs = Q()
    topic_ids = list(p.categories.values_list("topic_id", flat=True).distinct())
    if topic_ids:
        prefs &= Q(interests__in=topic_ids)

    if p.neighbourhood_id:  # neighbourhood proposal; city-wide ones reach every area
        place = (Q(area_type=ResidentProfile.Area.CITY)
                 | Q(neighbourhood_id=p.neighbourhood_id)
                 | Q(postal_fsa__in=p.neighbourhood.postal_fsas or []))
        if p.location is not None:
            place |= Q(neighbourhood__boundary__contains=p.location)
        prefs &= place

    can_say = p.participation_open and p.status == Proposal.Status.ONGOING
    if not can_say:  # "open" means: only tell me while I can have a say
        prefs &= Q(notify_trigger=ResidentProfile.Trigger.EVERY)

    if not prefs:  # nothing to narrow by: everyone with app notifications on
        return base
    followers = Q(follow__proposal=p)
    return base.filter(prefs | followers).distinct()


# ---------------------------------------------------------------- what the message says

def message_for(p, kind, detail):
    where = p.neighbourhood.name if p.neighbourhood_id else "City-wide"
    demo = " (illustrative)" if p.is_illustrative else ""
    if kind == "new":
        title = f"New proposal: {p.title}"
        body = f"{where}{demo} · {p.summary}"
    else:
        title = p.title
        body = f"{detail}{demo}"
    if p.participation_open and p.status == Proposal.Status.ONGOING:
        body += " You can have a say."
    return title[:110], " ".join(body.split())[:230]


KIND_MAP = {"new": Notification.Kind.NEW, "changed": Notification.Kind.CHANGED,
            "update": Notification.Kind.UPDATE, "impact": Notification.Kind.IMPACT}


def notify_proposal(proposal, kind, detail="", update=None, impact=None):
    """Call from views. Runs after the database commit, in the background."""
    if not settings.PUSH_ALERTS_ENABLED or not proposal.is_published:
        return
    args = (proposal.pk, kind, detail, getattr(update, "pk", None), getattr(impact, "pk", None))
    transaction.on_commit(lambda: threading.Thread(target=_run, args=args, daemon=True).start())


def _run(proposal_pk, kind, detail, update_pk, impact_pk):
    close_old_connections()
    try:
        p = Proposal.objects.select_related("neighbourhood").get(pk=proposal_pk)
        n_kind = KIND_MAP[kind]
        title, body = message_for(p, kind, detail)
        residents = list(residents_for(p).values_list("pk", flat=True))

        if kind == "changed":  # small edits: at most one alert per proposal per cooldown period
            since = timezone.now() - timedelta(hours=settings.ALERT_COOLDOWN_HOURS)
            recent = set(Notification.objects.filter(resident_id__in=residents, proposal=p, created_at__gte=since)
                         .values_list("resident_id", flat=True))
            residents = [r for r in residents if r not in recent]
        if not residents:
            return

        # Save to the bell first (followers may already have this update/impact: duplicates are ignored).
        Notification.objects.bulk_create(
            [Notification(resident_id=r, kind=n_kind, proposal=p, update_id=update_pk, impact_id=impact_pk,
                          text=f"{p.title}: {detail}"[:300] if kind == "changed" else "")
             for r in residents],
            ignore_conflicts=True)

        tokens = list(DeviceToken.objects.filter(resident_id__in=residents, is_active=True).values_list("token", flat=True))
        sent = send_push(tokens, title, body, {"proposal_id": p.pk, "kind": kind}) if tokens else 0
        if sent:
            Notification.objects.filter(resident_id__in=residents, proposal=p, kind=n_kind, sent_push_at__isnull=True) \
                .update(sent_push_at=timezone.now())
        log.info("Push for proposal %s (%s): %s residents, %s devices, %s sent", p.pk, kind, len(residents), len(tokens), sent)
    except Exception:
        log.exception("Push alerts failed for proposal %s", proposal_pk)
    finally:
        close_old_connections()
