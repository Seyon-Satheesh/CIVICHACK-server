"""CivicSpeak admin console – forms."""
from django import forms
from django.contrib.gis.geos import Point
from django.forms import inlineformset_factory

from .models import (Category, CommunityPost, Impact, Neighbourhood, Proposal, ProposalPoint,
                     Source, StatusUpdate, TimelineStep)


class MultipleFileInput(forms.ClearableFileInput):
    """Django needs this subclass to accept several files in one input."""
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput())
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        single = super().clean
        if isinstance(data, (list, tuple)):
            return [single(d, initial) for d in data]
        return single(data, initial)


def lines(text):
    return [line.strip() for line in (text or "").splitlines() if line.strip()]


class ProposalForm(forms.ModelForm):
    """Main proposal form. Bullet lists are typed one per line, like the demo, and saved as ProposalPoints."""
    changes = forms.CharField(label="What's changing (one per line)", widget=forms.Textarea(attrs={"rows": 3}))
    pros = forms.CharField(label="Pros (one per line)", required=False, widget=forms.Textarea(attrs={"rows": 3}))
    cons = forms.CharField(label="Cons (one per line)", required=False, widget=forms.Textarea(attrs={"rows": 3}))
    actions = forms.CharField(label="What residents can do (one per line)", required=False,
                              widget=forms.Textarea(attrs={"rows": 3}))
    latitude = forms.FloatField(required=False, widget=forms.HiddenInput)   # set by clicking the map
    longitude = forms.FloatField(required=False, widget=forms.HiddenInput)
    source_url = forms.URLField(label="Source document link", required=False)
    source_title = forms.CharField(label="Source document title", required=False)
    source_kind = forms.ChoiceField(choices=Source.Kind.choices, required=False)
    source_files = MultipleFileField(label="Source documents", required=False)

    class Meta:
        model = Proposal
        fields = ["title", "summary", "affected", "stage", "status", "address", "neighbourhood",
                  "impact_radius_km", "categories", "participation_open", "participation_url",
                  "participation_deadline", "cost_estimate", "cost_note", "expected_timing", "budget_line",
                  "is_illustrative"]
        widgets = {
            "summary": forms.Textarea(attrs={"rows": 3}),
            "affected": forms.Textarea(attrs={"rows": 2}),
            "stage": forms.RadioSelect, "status": forms.RadioSelect,
            "categories": forms.CheckboxSelectMultiple,
            "participation_deadline": forms.DateTimeInput(attrs={"type": "datetime-local"}),
        }
        help_texts = {
            "participation_deadline": "Only enter a deadline that is published on the official page. A meeting date is not a deadline.",
            "summary": "Plain language. Residents read this first.",
        }

    def __init__(self, *args, municipality=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.municipality = municipality
        self.fields["neighbourhood"].queryset = Neighbourhood.objects.filter(municipality=municipality)
        self.fields["neighbourhood"].required = False
        self.fields["neighbourhood"].empty_label = "City-wide"
        self.fields["categories"].queryset = Category.objects.order_by("name")
        p = self.instance
        if p.pk:
            for kind, name in [("change", "changes"), ("pro", "pros"), ("con", "cons"), ("action", "actions")]:
                self.fields[name].initial = "\n".join(p.points.filter(kind=kind).values_list("text", flat=True))
            if p.location:
                self.fields["longitude"].initial, self.fields["latitude"].initial = p.location.x, p.location.y

    def clean(self):
        data = super().clean()
        if data.get("participation_open"):
            if data.get("status") != Proposal.Status.ONGOING:
                self.add_error("participation_open", "Only ongoing proposals can be open for input.")
            if not data.get("participation_url"):
                self.add_error("participation_url", "Add the official page where residents can take part.")
            if not lines(data.get("actions")):
                self.add_error("actions", "List at least one thing residents can do.")
        if data.get("source_url") and not data.get("source_title"):
            self.add_error("source_title", "Give the source document a title.")
        lat, lng = data.get("latitude"), data.get("longitude")
        if data.get("neighbourhood") and (lat is None or lng is None):
            self.add_error(None, "Place the pin on the map.")
        return data

    def save_points(self, proposal):
        proposal.points.all().delete()
        bulk = []
        for kind, name in [("change", "changes"), ("pro", "pros"), ("con", "cons"), ("action", "actions")]:
            bulk += [ProposalPoint(proposal=proposal, kind=kind, text=t, order=i)
                     for i, t in enumerate(lines(self.cleaned_data.get(name)))]
        ProposalPoint.objects.bulk_create(bulk)

    def apply_location(self, proposal):
        lat, lng = self.cleaned_data.get("latitude"), self.cleaned_data.get("longitude")
        proposal.location = Point(lng, lat, srid=4326) if lat is not None and lng is not None else None


TimelineFormSet = inlineformset_factory(
    Proposal, TimelineStep,
    fields=["order", "label", "level", "state", "date", "date_confirmed", "note", "residents_can_participate"],
    extra=1, can_delete=True,
)


class StatusUpdateForm(forms.ModelForm):
    class Meta:
        model = StatusUpdate
        fields = ["title", "importance", "summary"]
        widgets = {"importance": forms.RadioSelect, "summary": forms.Textarea(attrs={"rows": 4})}


class ImpactForm(forms.ModelForm):
    class Meta:
        model = Impact
        fields = ["kind", "observed_on", "text"]
        widgets = {"kind": forms.RadioSelect, "observed_on": forms.DateInput(attrs={"type": "date"}),
                   "text": forms.Textarea(attrs={"rows": 2})}


class CommunityPostForm(forms.ModelForm):
    community_did_text = forms.CharField(label="What the community did (one per line)", widget=forms.Textarea(attrs={"rows": 3}))
    what_changed_text = forms.CharField(label="What changed because of it (one per line)", widget=forms.Textarea(attrs={"rows": 3}))

    class Meta:
        model = CommunityPost
        fields = ["title", "thanks", "highlighted_feedback"]
        widgets = {"highlighted_feedback": forms.CheckboxSelectMultiple}

    def __init__(self, *args, proposal=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.proposal = proposal or self.instance.proposal
        self.instance.proposal = self.proposal   # so model validation can check the proposal is completed
        # Staff can feature resident comments, never hidden ones.
        self.fields["highlighted_feedback"].queryset = self.proposal.feedback.filter(is_hidden=False).exclude(comment="")
        self.fields["highlighted_feedback"].required = False
        self.fields["highlighted_feedback"].label_from_instance = lambda fb: f"{fb.get_choice_display()}: {fb.comment}"
        if self.instance.pk:
            self.fields["community_did_text"].initial = "\n".join(self.instance.community_did)
            self.fields["what_changed_text"].initial = "\n".join(self.instance.what_changed)
        else:
            self.fields["title"].initial = f"{self.proposal.title} is complete, thanks to neighbours who spoke up"
            self.fields["thanks"].initial = "Thank you to everyone who shared their view."

    def clean(self):
        data = super().clean()
        if self.proposal.status != "completed":
            raise forms.ValidationError("Community posts are only for completed proposals.")
        data["community_did"] = lines(data.get("community_did_text"))
        data["what_changed"] = lines(data.get("what_changed_text"))
        if not data["community_did"] or not data["what_changed"]:
            raise forms.ValidationError("Add what the community did and what changed.")
        return data
