"""One place to announce proposal changes to residents: app push notifications and text messages."""
from . import push, sms


def proposal_event(proposal, kind, detail="", update=None, impact=None):
    """kind: "new" (just published), "changed" (status, stage, input open/closed, summary),
    "update" (staff posted an update) or "impact" (a completed proposal got a new impact)."""
    push.notify_proposal(proposal, kind, detail, update=update, impact=impact)
    sms.notify_proposal(proposal, "update" if kind == "impact" else kind, detail)
