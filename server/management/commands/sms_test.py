"""Sends one real test text through Twilio to check the keys and number work.

    python manage.py sms_test +14165550000
"""
from django.core.management.base import BaseCommand

from server.models import Municipality, SmsSubscriber
from server.sms import send_sms


class Command(BaseCommand):
    help = "Sends a test text message through Twilio."

    def add_arguments(self, parser):
        parser.add_argument("phone", help="E.164 format, e.g. +14165550000")

    def handle(self, phone, **opts):
        muni = Municipality.objects.order_by("pk").first()
        sub, _ = SmsSubscriber.objects.get_or_create(phone=phone, defaults={"municipality": muni})
        msg = send_sms(sub, "CivicSpeak test message. If you got this, text alerts are working.")
        self.stdout.write(f"Status: {msg.status} {msg.twilio_sid} {msg.error}")
