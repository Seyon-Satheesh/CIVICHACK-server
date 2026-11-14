"""Twilio webhooks for CivicSpeak text alerts.

In the Twilio console, set your phone number's "A message comes in" webhook to
    https://<your-domain>/sms/twilio/     (HTTP POST)
and (optional) the status callback to
    https://<your-domain>/sms/twilio/status/
"""
import logging

from django.conf import settings
from django.http import HttpResponse, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .models import SmsMessage
from .sms import handle_incoming

log = logging.getLogger(__name__)


def _valid_twilio_request(request):
    """Checks the X-Twilio-Signature header so nobody else can post fake texts to this URL."""
    token = settings.TWILIO_AUTH_TOKEN
    if not token:
        # Only allowed while developing locally without Twilio.
        return settings.DEBUG
    from twilio.request_validator import RequestValidator
    # Behind Coolify's proxy, set TWILIO_WEBHOOK_URL to the exact URL saved in Twilio if validation fails.
    url = settings.TWILIO_WEBHOOK_URL or request.build_absolute_uri()
    if request.path.endswith("/status/") and settings.TWILIO_WEBHOOK_URL:
        url = settings.TWILIO_WEBHOOK_URL.rstrip("/") + "/status/"
    signature = request.headers.get("X-Twilio-Signature", "")
    return RequestValidator(token).validate(url, request.POST.dict(), signature)


def _twiml(reply):
    from twilio.twiml.messaging_response import MessagingResponse
    resp = MessagingResponse()
    if reply:
        resp.message(reply)
    return HttpResponse(str(resp), content_type="application/xml")


@csrf_exempt
@require_POST
def incoming_sms(request):
    if not _valid_twilio_request(request):
        log.warning("Rejected SMS webhook call with an invalid Twilio signature")
        return HttpResponseForbidden("Invalid signature")
    phone = request.POST.get("From", "").strip()
    if not phone:
        return _twiml("")
    try:
        reply = handle_incoming(phone, request.POST.get("Body", ""))
    except Exception:
        log.exception("Error handling SMS from %s", phone[:-4] + "****")
        reply = "Sorry, something went wrong. Please try again in a few minutes."
    return _twiml(reply)


@csrf_exempt
@require_POST
def sms_status(request):
    """Delivery status updates from Twilio (queued → sent → delivered / failed)."""
    if not _valid_twilio_request(request):
        return HttpResponseForbidden("Invalid signature")
    sid, status = request.POST.get("MessageSid", ""), request.POST.get("MessageStatus", "")
    if sid and status:
        SmsMessage.objects.filter(twilio_sid=sid).update(status=status, error=request.POST.get("ErrorCode", "")[:300])
    return HttpResponse(status=204)
