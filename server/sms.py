"""CivicSpeak by text message (Twilio).

People without the app text the CivicSpeak number to sign up:
  1. their address (we keep only the first 3 characters of the postal code),
  2. the topics they care about,
  3. near me or the whole city.
After that they get a text whenever a matching proposal is added or updated.

Settings come from environment variables (see backend/settings.py):
  TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER or TWILIO_MESSAGING_SERVICE_SID,
  SMS_ALERTS_ENABLED, SMS_COOLDOWN_HOURS, TWILIO_WEBHOOK_URL (optional).
If Twilio isn't configured, texts are logged (status "not_configured") instead of sent.
"""
import logging
import re
import threading
from datetime import timedelta

from django.conf import settings
from django.db import close_old_connections, transaction
from django.db.models import Q
from django.utils import timezone

from .models import Municipality, Proposal, SmsMessage, SmsSubscriber, Topic

log = logging.getLogger(__name__)

# Canadian postal code: first 3 characters (FSA), optional last 3.
POSTAL_RE = re.compile(r"\b([ABCEGHJ-NPRSTVXY]\d[ABCEGHJ-NPRSTV-Z])\s?(\d[ABCEGHJ-NPRSTV-Z]\d)?\b", re.I)

# Twilio handles these opt-out / opt-in keywords itself (and replies). We only record them.
STOP_WORDS = {"STOP", "STOPALL", "UNSUBSCRIBE", "CANCEL", "END", "QUIT", "REVOKE", "OPTOUT"}
START_WORDS = {"START", "UNSTOP", "YES"}

TOPIC_ORDER = ["planning", "roads", "parks", "bylaws", "budget", "safety", "water", "community"]
SHORT_LABELS = {
    "planning": "Housing & planning", "roads": "Roads & transit", "parks": "Parks & recreation",
    "bylaws": "Bylaws", "budget": "Budget & taxes", "safety": "Safety", "water": "Water & waste",
    "community": "Community services",
}
MAX_LEN = 320  # about 2 SMS segments


# ---------------------------------------------------------------- sending

def _client():
    sid, token = settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN
    if not (sid and token and (settings.TWILIO_PHONE_NUMBER or settings.TWILIO_MESSAGING_SERVICE_SID)):
        return None
    from twilio.rest import Client  # imported here so the app still starts without Twilio settings
    return Client(sid, token)


def send_sms(subscriber, body, proposal=None):
    """Sends one text and logs it. Never raises: a failed text must not break publishing."""
    body = body[:MAX_LEN]
    msg = SmsMessage.objects.create(subscriber=subscriber, direction=SmsMessage.Direction.OUT, body=body, proposal=proposal)
    client = _client()
    if client is None:
        msg.status = "not_configured"
        msg.save(update_fields=["status"])
        log.info("SMS not sent (Twilio not configured) to %s: %s", subscriber, body)
        return msg
    kwargs = {"to": subscriber.phone, "body": body}
    if settings.TWILIO_MESSAGING_SERVICE_SID:
        kwargs["messaging_service_sid"] = settings.TWILIO_MESSAGING_SERVICE_SID
    else:
        kwargs["from_"] = settings.TWILIO_PHONE_NUMBER
    try:
        sent = client.messages.create(**kwargs)
        msg.twilio_sid, msg.status = sent.sid, sent.status or "queued"
    except Exception as exc:  # TwilioRestException, network errors...
        msg.status, msg.error = "failed", str(exc)[:300]
        log.warning("SMS to %s failed: %s", subscriber, exc)
        # 21610 = the person texted STOP; keep our records in sync.
        if getattr(exc, "code", None) == 21610:
            SmsSubscriber.objects.filter(pk=subscriber.pk).update(is_active=False, opted_out_at=timezone.now())
    msg.save(update_fields=["twilio_sid", "status", "error"])
    return msg


# ---------------------------------------------------------------- who gets a text about a proposal

def subscribers_for(proposal):
    """Active, signed-up subscribers whose topics and area match the proposal."""
    qs = SmsSubscriber.objects.filter(municipality=proposal.municipality, is_active=True, step=SmsSubscriber.Step.DONE)

    topic_ids = list(proposal.categories.values_list("topic_id", flat=True).distinct())
    if topic_ids:
        qs = qs.filter(interests__in=topic_ids)

    hood = proposal.neighbourhood
    if hood is not None:  # neighbourhood proposal: whole-city subscribers + people whose postal code is in it
        qs = qs.filter(Q(area=SmsSubscriber.Area.CITY) | Q(area=SmsSubscriber.Area.NEAR, postal_fsa__in=hood.postal_fsas or []))
    # No neighbourhood = city-wide, so everyone with matching topics.
    return qs.distinct()


def _short(text, n):
    text = " ".join((text or "").split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def _say_line(p):
    if p.participation_open and p.participation_url:
        when = f" until {timezone.localtime(p.participation_deadline):%b %-d}" if p.participation_deadline else ""
        return f"You can have a say{when}: {p.participation_url}"
    return ""


def alert_text(proposal, kind, detail=""):
    p = proposal
    where = f" ({p.neighbourhood.name})" if p.neighbourhood_id else " (city-wide)"
    demo = " [illustrative example]" if p.is_illustrative else ""
    if kind == "new":
        head = f"CivicSpeak: New proposal{where}{demo}: {p.title}. {_short(p.summary, 120)}"
    else:
        head = f"CivicSpeak update{where}{demo}: {p.title}. {_short(detail, 140)}"
    say = _say_line(p)
    return f"{head} {say}".strip()


def notify_proposal(proposal, kind, detail=""):
    """Call from views after publishing or updating. Sends after the database commit, in the background,
    so staff aren't kept waiting and the proposal's categories are already saved."""
    if not settings.SMS_ALERTS_ENABLED or not proposal.is_published:
        return
    pk = proposal.pk
    transaction.on_commit(lambda: threading.Thread(target=_send_alerts, args=(pk, kind, detail), daemon=True).start())


def _send_alerts(proposal_pk, kind, detail):
    close_old_connections()
    try:
        p = Proposal.objects.select_related("neighbourhood").get(pk=proposal_pk)
        body = alert_text(p, kind, detail)
        cooldown = timezone.now() - timedelta(hours=settings.SMS_COOLDOWN_HOURS)
        count = 0
        for sub in subscribers_for(p):
            # Small edits shouldn't spam: at most one "changed" text per proposal per cooldown period.
            if kind == "changed" and SmsMessage.objects.filter(
                    subscriber=sub, proposal=p, direction=SmsMessage.Direction.OUT, created_at__gte=cooldown).exists():
                continue
            send_sms(sub, body, proposal=p)
            count += 1
        log.info("SMS alerts for proposal %s (%s): %s sent", p.pk, kind, count)
    except Exception:
        log.exception("SMS alerts failed for proposal %s", proposal_pk)
    finally:
        close_old_connections()


def describe_changes(old, p):
    """Plain-language summary of what changed on a proposal, or "" if nothing residents need to hear about."""
    if old is None:
        return ""
    changes = []
    if old["status"] != p.status:
        changes.append({"completed": "It was completed.", "abandoned": "It is no longer going ahead.",
                        "ongoing": "It is active again."}.get(p.status, f"Status: {p.get_status_display()}."))
    if old["stage"] != p.stage and p.status == "ongoing":
        changes.append(f"It moved to the {p.get_stage_display().lower()} stage.")
    if not old["participation_open"] and p.participation_open:
        changes.append("Input is now open.")
    elif old["participation_open"] and not p.participation_open:
        changes.append("Input is now closed.")
    if old["summary"] != p.summary and not changes:
        changes.append("The summary was updated.")
    return " ".join(changes)


# ---------------------------------------------------------------- the sign-up conversation

def topics_menu():
    lines = [f"{i}. {SHORT_LABELS[k]}" for i, k in enumerate(TOPIC_ORDER, 1)]
    return "Which topics do you want texts about? Reply with numbers, e.g. 1 2 5, or ALL.\n" + "\n".join(lines)


AREA_MENU = "Which proposals? Reply 1 for near me (your neighbourhood + city-wide) or 2 for the whole city."
COMMANDS = "Text TOPICS, AREA or ADDRESS to change your choices, SETTINGS to see them, STOP to unsubscribe."


def settings_text(sub):
    topics = ", ".join(SHORT_LABELS.get(k, k) for k in sub.interests.order_by("key").values_list("key", flat=True)) or "none"
    area = "near you" if sub.area == SmsSubscriber.Area.NEAR else "the whole city"
    return f"Your CivicSpeak texts: {topics}; {area}; postal area {sub.postal_fsa or 'not set'}."


def _parse_topics(text):
    t = text.strip().upper()
    if t in {"ALL", "ALL OF THEM", "EVERYTHING"}:
        return list(TOPIC_ORDER)
    nums = re.findall(r"\d+", t)
    picked = [TOPIC_ORDER[int(n) - 1] for n in nums if 1 <= int(n) <= len(TOPIC_ORDER)]
    return list(dict.fromkeys(picked))  # keep order, drop repeats


def _neighbourhood_names(sub):
    return list(sub.municipality.neighbourhoods.filter(postal_fsas__contains=[sub.postal_fsa]).values_list("name", flat=True))


def _handle_address(sub, text):
    m = POSTAL_RE.search(text.upper())
    if not m:
        return "Please reply with your address including your postal code, e.g. 100 Queen St W, M5H 2N2."
    sub.postal_fsa = m.group(1).upper()
    hoods = _neighbourhood_names(sub)
    if sub.signed_up_at:  # changing address after sign-up
        sub.step = SmsSubscriber.Step.DONE
        sub.save()
        where = f" ({', '.join(hoods)})" if hoods else ""
        return f"Got it, postal area {sub.postal_fsa}{where}. {settings_text(sub)}"
    sub.step = SmsSubscriber.Step.TOPICS
    sub.save()
    where = f"That's in {', '.join(hoods)}. " if hoods else ""
    return f"Thanks! We only keep {sub.postal_fsa}, not your full address. {where}{topics_menu()}"


def _handle_topics(sub, text):
    keys = _parse_topics(text)
    if not keys:
        return "Sorry, I didn't get that. " + topics_menu()
    sub.interests.set(Topic.objects.filter(key__in=keys))
    if sub.signed_up_at:
        sub.step = SmsSubscriber.Step.DONE
        sub.save()
        return f"Topics updated. {settings_text(sub)}"
    sub.step = SmsSubscriber.Step.AREA
    sub.save()
    return AREA_MENU


def _handle_area(sub, text):
    t = text.strip().upper()
    if t in {"1", "NEAR", "NEAR ME"}:
        sub.area = SmsSubscriber.Area.NEAR
    elif t in {"2", "CITY", "WHOLE CITY", "ALL"}:
        sub.area = SmsSubscriber.Area.CITY
    else:
        return "Sorry, I didn't get that. " + AREA_MENU
    first_time = sub.signed_up_at is None
    sub.step = SmsSubscriber.Step.DONE
    sub.signed_up_at = sub.signed_up_at or timezone.now()
    sub.save()
    note = ""
    if sub.area == SmsSubscriber.Area.NEAR and not _neighbourhood_names(sub):
        note = " We haven't matched your postal area to a neighbourhood yet, so for now you'll get city-wide proposals."
    if first_time:
        return f"You're signed up! We'll text you when a proposal that matches is added or updated.{note} {COMMANDS}"
    return f"Area updated. {settings_text(sub)}{note}"


def handle_incoming(phone, text):
    """Returns the reply to send back, or "" for no reply."""
    text = (text or "").strip()
    word = text.upper().strip(" .!")
    muni = Municipality.objects.order_by("pk").first()
    if muni is None:
        return "CivicSpeak text alerts aren't set up yet. Please try again later."

    sub = SmsSubscriber.objects.filter(phone=phone).first()
    if sub:
        SmsMessage.objects.create(subscriber=sub, direction=SmsMessage.Direction.IN, body=text[:1000])

    # Opt-out / opt-in: Twilio already replies to these, so we only update our records.
    if word in STOP_WORDS:
        if sub:
            sub.is_active, sub.opted_out_at = False, timezone.now()
            sub.save(update_fields=["is_active", "opted_out_at", "updated_at"])
        return ""
    if word in START_WORDS and sub and not sub.is_active:
        sub.is_active, sub.opted_out_at = True, None
        sub.save(update_fields=["is_active", "opted_out_at", "updated_at"])
        return ""

    if sub is None:
        sub = SmsSubscriber.objects.create(phone=phone, municipality=muni)
        SmsMessage.objects.create(subscriber=sub, direction=SmsMessage.Direction.IN, body=text[:1000])
        welcome = (f"Welcome to CivicSpeak text alerts for {muni.name}: updates on city proposals that matter to you. "
                   "Msg & data rates may apply. Reply STOP to unsubscribe.")
        if POSTAL_RE.search(text.upper()):  # they already sent their address
            return f"{welcome} {_handle_address(sub, text)}"
        return f"{welcome} To start, reply with your address including postal code, e.g. 100 Queen St W, M5H 2N2."

    if not sub.is_active:
        return ""  # opted out: Twilio blocks replies anyway

    # Commands that work any time.
    if word in {"HELP", "MENU", "INFO"}:
        return f"CivicSpeak text alerts. {COMMANDS}"
    if word in {"SETTINGS", "STATUS"}:
        return settings_text(sub) if sub.signed_up_at else "You haven't finished signing up yet. " + _prompt_for(sub)
    if word in {"TOPICS", "TOPIC"}:
        sub.step = SmsSubscriber.Step.TOPICS
        sub.save(update_fields=["step", "updated_at"])
        return topics_menu()
    if word == "AREA":
        sub.step = SmsSubscriber.Step.AREA
        sub.save(update_fields=["step", "updated_at"])
        return AREA_MENU
    if word in {"ADDRESS", "MOVE", "MOVED"}:
        sub.step = SmsSubscriber.Step.ADDRESS
        sub.save(update_fields=["step", "updated_at"])
        return "Reply with your new address including postal code, e.g. 100 Queen St W, M5H 2N2."

    if sub.step == SmsSubscriber.Step.ADDRESS:
        return _handle_address(sub, text)
    if sub.step == SmsSubscriber.Step.TOPICS:
        return _handle_topics(sub, text)
    if sub.step == SmsSubscriber.Step.AREA:
        return _handle_area(sub, text)
    return f"Thanks for your message. This number only sends alerts, so replies aren't read by city staff. {COMMANDS}"


def _prompt_for(sub):
    if sub.step == SmsSubscriber.Step.ADDRESS:
        return "Reply with your address including postal code."
    if sub.step == SmsSubscriber.Step.TOPICS:
        return topics_menu()
    return AREA_MENU
