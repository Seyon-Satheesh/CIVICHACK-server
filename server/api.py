"""
CivicSpeak resident API (JSON) used by the Flutter app.

Auth: POST /api/auth/register or /api/auth/login returns a token.
Send it on every other request as:  Authorization: Bearer <token>

Rules carried over from the design:
- Residents never receive vote totals (no tallies in any response).
- Only published proposals are shown, ranked by the resident's interests and area.
- Feedback is one per resident per proposal and can be updated; only while input is open.
- Only the first 3 characters of a postal code are stored.
"""
import json
import re
from functools import wraps

from django.contrib.auth import authenticate, get_user_model
from django.core import signing
from django.db import transaction
from django.db.models import Count, Q
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import (DeviceToken, CommunityPost, Feedback, Follow, Municipality, Neighbourhood, Notification, Proposal,
                     ResidentProfile, SurveyResponse, Topic)

TOKEN_SALT = "civicspeak.api"
TOKEN_MAX_AGE = 60 * 60 * 24 * 60  # 60 days
Q2_TO_TOPIC = {"building": "planning", "streets": "roads", "transit": "roads", "parks": "parks",
               "bylaws": "bylaws", "budget": "budget", "policing": "safety"}
FSA = re.compile(r"^[A-Z]\d[A-Z]$")


# ---------------------------------------------------------------- helpers

def error(message, status=400, field=None):
    body = {"error": message}
    if field:
        body["field"] = field
    return JsonResponse(body, status=status)


def body(request):
    try:
        return json.loads(request.body or b"{}")
    except (ValueError, UnicodeDecodeError):
        return None


def make_token(user):
    return signing.dumps({"u": user.pk}, salt=TOKEN_SALT)


def resident_required(view):
    """Reads the Bearer token and sets request.resident."""
    @csrf_exempt
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return error("Sign in required.", 401)
        try:
            data = signing.loads(header[7:], salt=TOKEN_SALT, max_age=TOKEN_MAX_AGE)
            resident = ResidentProfile.objects.select_related("user", "neighbourhood", "municipality").get(user_id=data["u"])
        except (signing.BadSignature, signing.SignatureExpired, KeyError, ResidentProfile.DoesNotExist):
            return error("Your session has expired. Please sign in again.", 401)
        if not resident.user.is_active:
            return error("This account is disabled.", 403)
        request.resident = resident
        return view(request, *args, **kwargs)
    return wrapper


def topic_keys_from_answers(answers):
    keys = {k for k in answers.get("q1", []) if k != "none"}
    keys |= {Q2_TO_TOPIC[k] for k in answers.get("q2", []) if k in Q2_TO_TOPIC}
    return keys


def money(value):
    return None if value is None else f"${value:,.0f}"


def latest_survey(resident):
    s = resident.survey_responses.order_by("-created_at").first()
    return s.answers if s else {}


def serialize_profile(r):
    return {
        "username": r.user.username,
        "email": r.user.email,
        "municipality": {"id": r.municipality_id, "name": r.municipality.name, "province": r.municipality.province},
        "area_type": r.area_type,
        "neighbourhood": {"id": r.neighbourhood_id, "name": r.neighbourhood.name} if r.neighbourhood else None,
        "postal_fsa": r.postal_fsa,
        "notify_trigger": r.notify_trigger,
        "notify_channels": r.notify_channels,
        "phone": r.phone,
        "language": r.language,
        "audio_mode": r.audio_mode,
        "large_text": r.large_text,
        "interests": sorted(r.interests.values_list("key", flat=True)),
        "answers": latest_survey(r),
        "following": list(Follow.objects.filter(resident=r).values_list("proposal_id", flat=True)),
    }


def apply_profile(resident, data, creating=False):
    """Validates and applies survey answers and settings. Returns an error response or None."""
    if "answers" in data:
        answers = data["answers"]
        if not isinstance(answers, dict):
            return error("Survey answers are missing.", field="answers")
        q2 = [k for k in answers.get("q2", []) if k != "read"]
        if len(q2) > 4:
            return error("Choose up to 4 decisions to have a say in.", field="q2")
    if "area_type" in data:
        if data["area_type"] not in ResidentProfile.Area.values:
            return error("Choose your whole city or your neighbourhood.", field="area_type")
        resident.area_type = data["area_type"]
        if resident.area_type == ResidentProfile.Area.NEIGHBOURHOOD:
            nb = Neighbourhood.objects.filter(pk=data.get("neighbourhood_id"), municipality=resident.municipality).first()
            if not nb:
                return error("Choose your neighbourhood.", field="neighbourhood_id")
            resident.neighbourhood = nb
        else:
            resident.neighbourhood = None
    if "postal_fsa" in data:
        fsa = (data.get("postal_fsa") or "").upper().replace(" ", "")[:3]
        if fsa and not FSA.match(fsa):
            return error("Use the first 3 characters of your postal code, like N2L.", field="postal_fsa")
        resident.postal_fsa = fsa
    if "notify_trigger" in data:
        if data["notify_trigger"] not in ResidentProfile.Trigger.values:
            return error("Choose when to be notified.", field="notify_trigger")
        resident.notify_trigger = data["notify_trigger"]
    if "notify_channels" in data:
        channels = [c for c in data["notify_channels"] if c in ("app", "email", "sms")]
        resident.notify_channels = channels
        if "email" in channels:
            email = (data.get("email") or resident.user.email or "").strip()
            if not re.match(r"^[^\s@]+@[^\s@]+\.[^\s@]+$", email):
                return error("Enter a valid email address.", field="email")
            resident.user.email = email
        if "sms" in channels:
            phone = (data.get("phone") or resident.phone or "").strip()
            if len(re.sub(r"\D", "", phone)) < 10:
                return error("Enter a 10-digit mobile number.", field="phone")
            resident.phone = phone
        else:
            resident.phone = ""
    for key in ("language", "audio_mode", "large_text"):
        if key in data:
            setattr(resident, key, data[key])
    if resident.language not in ("en", "fr", "es", "zh"):
        resident.language = "en"
    if creating:
        return None
    resident.user.save()
    resident.save()
    if "answers" in data:
        save_answers(resident, data["answers"])
    return None


def save_answers(resident, answers):
    SurveyResponse.objects.create(resident=resident, answers=answers)
    resident.interests.set(Topic.objects.filter(key__in=topic_keys_from_answers(answers)))


# ---------------------------------------------------------------- personalization

def personal_flags(resident, proposal, interest_ids, following_ids):
    cat_topics = {c.topic_id for c in proposal.categories.all()}
    matches = bool(cat_topics & interest_ids)
    near = bool(resident.neighbourhood_id and proposal.neighbourhood_id == resident.neighbourhood_id)
    return {
        "matches": matches,
        "near": near,
        "following": proposal.pk in following_ids,
        "score": (3 if near else 0) + (2 if matches else 0),
    }


def brief(proposal, flags):
    latest = proposal.updates.order_by("-created_at").first()
    return {
        "id": proposal.pk,
        "title": proposal.title,
        "summary": proposal.summary,
        "status": proposal.status,
        "stage": proposal.stage,
        "stage_label": proposal.get_stage_display(),
        "neighbourhood": proposal.neighbourhood.name if proposal.neighbourhood else "City-wide",
        "categories": [c.name for c in proposal.categories.all()],
        "is_illustrative": proposal.is_illustrative,
        "can_say": proposal.participation_open and proposal.status == Proposal.Status.ONGOING,
        "latest_update": {"title": latest.title, "date": latest.created_at.date().isoformat()} if latest else None,
        **{k: v for k, v in flags.items() if k != "score"},
    }


def ranked(resident, qs):
    interest_ids = set(resident.interests.values_list("pk", flat=True))
    following_ids = set(Follow.objects.filter(resident=resident).values_list("proposal_id", flat=True))
    items = []
    for p in qs.select_related("neighbourhood").prefetch_related("categories"):
        items.append((p, personal_flags(resident, p, interest_ids, following_ids)))
    # Higher score first; followed items first on the Completed and Abandoned tabs.
    items.sort(key=lambda x: (-(x[1]["following"] and x[0].status != "ongoing"), -x[1]["score"],
                              -(x[0].published_at.timestamp() if x[0].published_at else 0)))
    return items


def visible(resident):
    return Proposal.objects.filter(municipality=resident.municipality, is_published=True)


# ---------------------------------------------------------------- auth and profile

@csrf_exempt
@require_http_methods(["GET"])
def meta(request):
    """Public: what the onboarding survey needs (municipality, neighbourhoods, topics)."""
    muni = Municipality.objects.order_by("pk").first()
    if not muni:
        return error("CivicSpeak is not set up yet.", 503)
    return JsonResponse({
        "municipality": {"id": muni.pk, "name": muni.name, "province": muni.province,
                         "official_participation_url": muni.official_participation_url},
        "neighbourhoods": [{"id": n.pk, "name": n.name} for n in muni.neighbourhoods.order_by("name")],
        "topics": [{"key": t.key, "label": t.label} for t in Topic.objects.order_by("label")],
    })


@csrf_exempt
@require_http_methods(["POST"])
def register(request):
    data = body(request)
    if data is None:
        return error("Invalid request.")
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not re.match(r"^[A-Za-z0-9_.-]{2,24}$", username):
        return error("Use 2 to 24 letters, numbers, dots, dashes or underscores.", field="username")
    if len(password) < 8:
        return error("Use at least 8 characters for your password.", field="password")
    User = get_user_model()
    if User.objects.filter(username__iexact=username).exists():
        return error("That username is taken. Try another.", field="username")
    muni = Municipality.objects.filter(pk=data.get("municipality_id")).first() or Municipality.objects.order_by("pk").first()
    if not muni:
        return error("CivicSpeak is not set up yet.", 503)
    with transaction.atomic():
        user = User.objects.create_user(username=username, password=password)
        resident = ResidentProfile(user=user, municipality=muni, area_type=ResidentProfile.Area.CITY)
        problem = apply_profile(resident, data, creating=True)
        if problem:
            transaction.set_rollback(True)
            return problem
        user.save()
        resident.save()
        save_answers(resident, data.get("answers") or {})
    return JsonResponse({"token": make_token(user), "profile": serialize_profile(resident)}, status=201)


@csrf_exempt
@require_http_methods(["POST"])
def login(request):
    data = body(request) or {}
    user = authenticate(request, username=(data.get("username") or "").strip(), password=data.get("password") or "")
    if not user or not hasattr(user, "resident"):
        return error("Username or password is incorrect.", 401)
    return JsonResponse({"token": make_token(user), "profile": serialize_profile(user.resident)})


@resident_required
@require_http_methods(["GET", "PATCH"])
def me(request):
    r = request.resident
    if request.method == "PATCH":
        data = body(request)
        if data is None:
            return error("Invalid request.")
        problem = apply_profile(r, data)
        if problem:
            return problem
    return JsonResponse({"profile": serialize_profile(r)})


# ---------------------------------------------------------------- proposals

@resident_required
@require_http_methods(["GET"])
def proposals(request):
    """GET /api/proposals?status=ongoing|completed|abandoned  (personalized order)"""
    status = request.GET.get("status", "ongoing")
    if status not in Proposal.Status.values:
        return error("Unknown status.")
    items = ranked(request.resident, visible(request.resident).filter(status=status))
    return JsonResponse({"results": [brief(p, f) for p, f in items]})


@resident_required
@require_http_methods(["GET"])
def proposal_detail(request, pk):
    r = request.resident
    p = visible(r).select_related("neighbourhood").prefetch_related("categories").filter(pk=pk).first()
    if not p:
        return error("Proposal not found.", 404)
    interest_ids = set(r.interests.values_list("pk", flat=True))
    following_ids = set(Follow.objects.filter(resident=r).values_list("proposal_id", flat=True))
    flags = personal_flags(r, p, interest_ids, following_ids)
    points = {"change": [], "pro": [], "con": [], "action": []}
    for pt in p.points.order_by("order"):
        points[pt.kind].append(pt.text)
    mine = Feedback.objects.filter(proposal=p, resident=r).first()
    data = brief(p, flags)
    data.update({
        "affected": p.affected,
        "address": p.address,
        "lat": p.location.y if p.location else None,
        "lng": p.location.x if p.location else None,
        "radius_km": float(p.impact_radius_km) if p.impact_radius_km is not None else None,
        "changes": points["change"], "pros": points["pro"], "cons": points["con"], "actions": points["action"],
        "steps": [{"label": s.label, "level": s.level, "level_label": s.get_level_display(), "state": s.state,
                   "state_label": s.get_state_display(), "date": s.date.isoformat() if s.date else None,
                   "date_confirmed": s.date_confirmed, "note": s.note,
                   "can_participate": s.residents_can_participate}
                  for s in p.steps.order_by("order")],
        "sources": [{"kind": s.get_kind_display(), "title": s.title, "url": s.url,
                     "date": s.published_on.isoformat() if s.published_on else None}
                    for s in p.sources.order_by("-published_on")],
        "updates": [{"title": u.title, "summary": u.summary, "importance": u.get_importance_display(),
                     "date": u.created_at.date().isoformat()} for u in p.updates.order_by("-created_at")],
        "impacts": [{"kind": i.kind, "text": i.text, "date": i.observed_on.isoformat()} for i in p.impacts.order_by("-observed_on")],
        "cost": {"estimate": money(p.cost_estimate) or p.cost_note or "Not stated",
                 "note": p.cost_note, "payers": list(p.payers.values_list("name", flat=True)) or ["Not stated"],
                 "when": p.expected_timing or "Not stated", "budget_line": p.budget_line},
        "participation": {"open": data["can_say"], "url": p.participation_url,
                          "deadline": p.participation_deadline.isoformat() if p.participation_deadline else None},
        "my_feedback": {"choice": mine.choice, "comment": mine.comment} if mine else None,
    })
    return JsonResponse(data)


@resident_required
@require_http_methods(["POST"])
def follow(request, pk):
    p = visible(request.resident).filter(pk=pk).first()
    if not p:
        return error("Proposal not found.", 404)
    obj, created = Follow.objects.get_or_create(resident=request.resident, proposal=p)
    if not created:
        obj.delete()
    return JsonResponse({"following": created})


@resident_required
@require_http_methods(["POST"])
def feedback(request, pk):
    data = body(request) or {}
    p = visible(request.resident).filter(pk=pk).first()
    if not p:
        return error("Proposal not found.", 404)
    if not (p.participation_open and p.status == Proposal.Status.ONGOING):
        return error("Input on this proposal is closed.", 409)
    choice = data.get("choice")
    if choice not in Feedback.Choice.values:
        return error("Choose Support, Neutral or Oppose.", field="choice")
    comment = (data.get("comment") or "").strip()[:500]
    fb, created = Feedback.objects.update_or_create(
        proposal=p, resident=request.resident,
        defaults={"choice": choice, "comment": comment, "channel": Feedback.Channel.APP})
    # No totals in the response: residents should not be swayed by the crowd.
    return JsonResponse({"saved": True, "updated": not created, "my_feedback": {"choice": fb.choice, "comment": fb.comment}})


@resident_required
@require_http_methods(["GET"])
def funding(request, pk):
    p = visible(request.resident).filter(pk=pk).first()
    if not p:
        return error("Proposal not found.", 404)
    allocations = []
    for a in p.allocations.select_related("statement__fund", "statement__source"):
        st = a.statement
        allocations.append({
            "fund": st.fund.name, "year": st.year,
            "allocated": money(a.allocated), "spent": money(a.spent),
            "percent_spent": round(float(a.spent) * 100 / float(a.allocated)) if a.allocated else 0,
            "statement": {"collected": money(st.collected), "draws": money(st.draws), "closing_balance": money(st.closing_balance),
                          "source": {"title": st.source.title, "url": st.source.url}},
        })
    return JsonResponse({
        "id": p.pk, "title": p.title,
        "cost": {"estimate": money(p.cost_estimate) or p.cost_note or "Not stated",
                 "payers": list(p.payers.values_list("name", flat=True)) or ["Not stated"],
                 "when": p.expected_timing or "Not stated", "budget_line": p.budget_line},
        "allocations": allocations,
    })


@resident_required
@require_http_methods(["GET"])
def map_pins(request):
    """GET /api/map?status=ongoing|completed&only_following=1   (abandoned proposals are never on the map)"""
    r = request.resident
    status = request.GET.get("status", "ongoing")
    if status not in ("ongoing", "completed"):
        return error("The map shows ongoing or completed proposals.")
    qs = visible(r).filter(status=status, location__isnull=False)
    if request.GET.get("only_following") in ("1", "true"):
        qs = qs.filter(follow__resident=r)
    following_ids = set(Follow.objects.filter(resident=r).values_list("proposal_id", flat=True))
    pins = [{
        "id": p.pk, "title": p.title, "status": p.status,
        "lat": p.location.y, "lng": p.location.x,
        "radius_km": float(p.impact_radius_km) if p.impact_radius_km is not None else 0.5,
        "following": p.pk in following_ids,
        "cost": money(p.cost_estimate) or p.cost_note or "Not stated",
        "payers": list(p.payers.values_list("name", flat=True)) or ["Not stated"],
        "when": p.expected_timing or "Not stated",
    } for p in qs.distinct()]
    return JsonResponse({"pins": pins, "following_count": len(following_ids)})


# ---------------------------------------------------------------- community and notifications

@resident_required
@require_http_methods(["GET"])
def community(request):
    r = request.resident
    posts = (CommunityPost.objects.filter(proposal__municipality=r.municipality, published_at__isnull=False)
             .select_related("proposal__neighbourhood")
             .annotate(voices=Count("proposal__feedback", filter=Q(proposal__feedback__is_hidden=False)),
                       ideas=Count("proposal__feedback", filter=Q(proposal__feedback__is_hidden=False) & ~Q(proposal__feedback__comment="")))
             .order_by("-published_at"))
    total_voices = Feedback.objects.filter(proposal__municipality=r.municipality, is_hidden=False).count()
    used = Feedback.objects.filter(proposal__municipality=r.municipality, used_in_decision=True).count()
    return JsonResponse({
        "summary": {"voices_shared": total_voices, "projects_completed": posts.count(), "ideas_used": used},
        "posts": [{
            "id": po.pk, "title": po.title, "did": po.community_did, "changed": po.what_changed, "thanks": po.thanks,
            "date": po.published_at.date().isoformat(), "voices": po.voices, "ideas": po.ideas,
            "proposal": {"id": po.proposal_id, "title": po.proposal.title,
                         "neighbourhood": po.proposal.neighbourhood.name if po.proposal.neighbourhood else "City-wide"},
        } for po in posts],
    })


@resident_required
@require_http_methods(["GET"])
def notifications(request):
    r = request.resident
    items = []
    for n in r.notifications.select_related("proposal", "update", "impact", "post")[:100]:
        if n.kind == Notification.Kind.COMMUNITY and n.post:
            text = n.post.title
        elif n.kind == Notification.Kind.UPDATE and n.update:
            text = f"{n.proposal.title}: {n.update.title}"
        elif n.kind == Notification.Kind.IMPACT and n.impact:
            text = f"{n.proposal.title}: {n.impact.text}"
        elif n.text:
            text = n.text
        elif n.kind == Notification.Kind.NEW and n.proposal:
            text = f"New: {n.proposal.title}"
        else:
            text = n.proposal.title if n.proposal else ""
        items.append({"id": n.pk, "kind": n.kind, "text": text, "date": n.created_at.date().isoformat(),
                      "proposal_id": n.proposal_id, "read": n.read_at is not None})
    # Decisions near you or matching your interests that are open for input (not stored, always current).
    for p, f in ranked(r, visible(r).filter(status="ongoing", participation_open=True)):
        if f["near"] or f["matches"]:
            items.append({"id": None, "kind": "open", "text": p.title, "date": None, "proposal_id": p.pk, "read": True})
    unread = r.notifications.filter(read_at__isnull=True).count()
    return JsonResponse({"unread": unread, "results": items})


@resident_required
@require_http_methods(["POST"])
def notifications_read(request):
    request.resident.notifications.filter(read_at__isnull=True).update(read_at=timezone.now())
    return JsonResponse({"unread": 0})


# ---------------------------------------------------------------- push notification devices

@resident_required
@require_http_methods(["POST"])
def device_register(request):
    """The app sends its Firebase token after sign-in (and whenever it changes)."""
    data = body(request) or {}
    token = (data.get("token") or "").strip()
    platform = data.get("platform") or "android"
    if not token or len(token) > 512:
        return error("Missing device token.", field="token")
    if platform not in DeviceToken.Platform.values:
        platform = DeviceToken.Platform.ANDROID
    # A phone belongs to whoever signed in on it last.
    DeviceToken.objects.update_or_create(token=token, defaults={"resident": request.resident, "platform": platform, "is_active": True})
    return JsonResponse({"registered": True})


@resident_required
@require_http_methods(["POST"])
def device_unregister(request):
    """Called on sign-out so the phone stops getting this resident's notifications."""
    token = ((body(request) or {}).get("token") or "").strip()
    DeviceToken.objects.filter(token=token, resident=request.resident).delete()
    return JsonResponse({"registered": False})
