"""Try the text-message sign-up without a phone or Twilio.

    python manage.py sms_simulate +14165550000 "hi"
    python manage.py sms_simulate +14165550000 "100 Bloor St W, M5R 1A1"
    python manage.py sms_simulate +14165550000 "1 2 3"
    python manage.py sms_simulate +14165550000 "1"
    python manage.py sms_simulate +14165550000 --alerts   # show which proposals would text this number
"""
from django.core.management.base import BaseCommand

from server.models import Proposal, SmsSubscriber
from server.sms import alert_text, handle_incoming, subscribers_for


class Command(BaseCommand):
    help = "Simulates an incoming text message and prints CivicSpeak's reply."

    def add_arguments(self, parser):
        parser.add_argument("phone")
        parser.add_argument("message", nargs="?", default="")
        parser.add_argument("--alerts", action="store_true", help="List the published proposals this subscriber would be texted about")

    def handle(self, phone, message, alerts, **opts):
        if alerts:
            sub = SmsSubscriber.objects.filter(phone=phone).first()
            if not sub:
                self.stdout.write("No subscriber with that number yet.")
                return
            for p in Proposal.objects.filter(municipality=sub.municipality, is_published=True):
                if subscribers_for(p).filter(pk=sub.pk).exists():
                    self.stdout.write(f"- {alert_text(p, 'new')}\n")
            return
        self.stdout.write(f"> {message}")
        self.stdout.write(handle_incoming(phone, message) or "(no reply)")
