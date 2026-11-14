# from django.http import HttpResponse
# from django.shortcuts import render

# # Create your views here.
# def index(request):
#     return HttpResponse("Hello, world.")

"""
CivicSpeak admin console – views.

Matches the demo's admin screens:
  Proposals list (Current / Completed / Abandoned tabs with counts)
  Add / edit proposal (points, map pin, timeline, source), status updates, impacts
  Resident feedback (staff-only totals, mark helpful / used in decision, hide)
  Community posts (one per completed proposal; prompted when a proposal is completed)

Every view is limited to the signed-in staff member's municipality (StaffMembership).
Editors can publish; moderators can only work on feedback; viewers can only read.
"""
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.contrib.postgres.search import SearchQuery, SearchVector
from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.views import View
from django.views.generic import CreateView, DeleteView, ListView, UpdateView

from .forms import (CommunityPostForm, ImpactForm, ProposalForm, StatusUpdateForm, TimelineFormSet)
from . import alerts
from .models import (CommunityPost, Feedback, Notification, Proposal, ResidentProfile, Source,
                     StaffMembership)


# ---------------------------------------------------------------- access

class StaffMixin(LoginRequiredMixin, UserPassesTestMixin):
    """Signed-in staff only, scoped to their municipality. `roles` lists who may use the view."""
    roles = (StaffMembership.Role.EDITOR, StaffMembership.Role.MODERATOR, StaffMembership.Role.VIEWER)

    def test_func(self):
        staff = getattr(self.request.user, "staff", None)
        return bool(staff and staff.role in self.roles)

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        role = self.request.user.staff.role
        ctx["can_edit"] = role == StaffMembership.Role.EDITOR
        ctx["can_moderate"] = role in (StaffMembership.Role.EDITOR, StaffMembership.Role.MODERATOR)
        return ctx

    @property
    def municipality(self):
        return self.request.user.staff.municipality

    def proposals(self):
        return Proposal.objects.filter(municipality=self.municipality)

    def get_proposal(self, pk=None):
        return get_object_or_404(self.proposals(), pk=pk or self.kwargs["pk"])


class EditorMixin(StaffMixin):
    roles = (StaffMembership.Role.EDITOR,)


class ModeratorMixin(StaffMixin):
    roles = (StaffMembership.Role.EDITOR, StaffMembership.Role.MODERATOR)


# ---------------------------------------------------------------- proposals

class ProposalListView(StaffMixin, ListView):
    """Proposals page with Current / Completed / Abandoned tabs and search."""
    template_name = "admin_console/proposal_list.html"
    context_object_name = "proposals"
    paginate_by = 24

    def get_status(self):
        s = self.request.GET.get("tab", Proposal.Status.ONGOING)
        return s if s in Proposal.Status.values else Proposal.Status.ONGOING

    def get_queryset(self):
        qs = (self.proposals().filter(status=self.get_status())
              .select_related("neighbourhood").prefetch_related("categories")
              .annotate(feedback_total=Count("feedback", filter=Q(feedback__is_hidden=False)),
                        comment_total=Count("feedback", filter=~Q(feedback__comment="") & Q(feedback__is_hidden=False))))
        q = self.request.GET.get("q", "").strip()
        if q:
            qs = qs.filter(search=SearchQuery(q))
        return qs.order_by("-updated_at")

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        counts = dict(self.proposals().order_by().values_list("status").annotate(n=Count("id")))
        ctx["tabs"] = [(s, label, counts.get(s, 0)) for s, label in
                       [("ongoing", "Current"), ("completed", "Completed"), ("abandoned", "Abandoned")]]
        ctx["active_tab"] = self.get_status()
        ctx["completed_without_post"] = self.proposals().filter(status="completed", community_post__isnull=True)
        return ctx


class ProposalFormMixin(EditorMixin):
    model = Proposal
    form_class = ProposalForm
    template_name = "admin_console/proposal_form.html"

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw["municipality"] = self.municipality
        return kw

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        if "timeline" not in ctx:
            ctx["timeline"] = TimelineFormSet(self.request.POST or None, instance=self.object or Proposal())
        return ctx

    @transaction.atomic
    def form_valid(self, form):
        timeline = TimelineFormSet(self.request.POST, instance=form.instance)
        if not timeline.is_valid():
            return self.render_to_response(self.get_context_data(form=form, timeline=timeline))
        was_completed = bool(form.instance.pk) and Proposal.objects.filter(pk=form.instance.pk, status="completed").exists()
        # What it looked like before, so text-message subscribers only hear about real changes.
        before = (Proposal.objects.filter(pk=form.instance.pk)
                  .values("status", "stage", "participation_open", "summary", "is_published").first()
                  if form.instance.pk else None)

        p = form.save(commit=False)
        p.municipality = self.municipality
        form.apply_location(p)
        if not p.slug:
            p.slug = slugify(p.title)[:70] or "proposal"
            if self.proposals().filter(slug=p.slug).exists():
                p.slug = f"{p.slug}-{timezone.now():%y%m%d%H%M}"
        if not p.pk:
            p.created_by = self.request.user
        if not p.is_published:
            p.is_published, p.published_at = True, timezone.now()
        p.save()
        form.save_m2m()
        form.save_points(p)
        timeline.instance = p
        timeline.save()

        url = form.cleaned_data.get("source_url")
        if url:
            src, _ = Source.objects.get_or_create(
                municipality=self.municipality, url=url,
                defaults={"title": form.cleaned_data["source_title"],
                          "kind": form.cleaned_data.get("source_kind") or Source.Kind.OTHER})
            p.sources.add(src)
        Proposal.objects.filter(pk=p.pk).update(search=SearchVector("title", weight="A") + SearchVector("summary", weight="B"))
        self.object = p

        # Text-message alerts go out after this transaction commits.
        if before is None or not before["is_published"]:
            alerts.proposal_event(p, "new")
        else:
            changed = sms.describe_changes(before, p)
            if changed:
                alerts.proposal_event(p, "changed", changed)

        # A newly completed proposal needs its community post: send staff straight to it.
        if p.status == "completed" and not was_completed and not hasattr(p, "community_post"):
            messages.info(self.request, "Saved. Now write the community post for this completed proposal.")
            return redirect("admin_console:post_create", pk=p.pk)
        messages.success(self.request, "Saved. Residents see the changes right away.")
        return redirect(f"{reverse('admin_console:proposal_list')}?tab={p.status}")


class ProposalCreateView(ProposalFormMixin, CreateView):
    pass


class ProposalUpdateView(ProposalFormMixin, UpdateView):
    """Editors can save; moderators and viewers can open the page to read it and work on feedback."""
    def test_func(self):
        staff = getattr(self.request.user, "staff", None)
        if not staff:
            return False
        if self.request.method == "POST":
            return staff.role == StaffMembership.Role.EDITOR
        return True

    def get_queryset(self):
        return self.proposals()

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        ctx["update_form"] = StatusUpdateForm()
        ctx["impact_form"] = ImpactForm() if self.object.status == "completed" else None
        ctx["updates"] = self.object.updates.all()
        ctx["impacts"] = self.object.impacts.all()
        ctx.update(feedback_context(self.object))
        return ctx


def feedback_context(proposal):
    """Staff-only totals and comments. Residents never get these numbers."""
    visible = proposal.feedback.filter(is_hidden=False)
    counts = dict(visible.order_by().values_list("choice").annotate(n=Count("id")))
    total = sum(counts.values())
    pct = {c: round(counts.get(c, 0) * 100 / total) if total else 0 for c in Feedback.Choice.values}
    return {
        "feedback_total": total, "feedback_counts": counts, "feedback_pct": pct,
        "feedback_comments": proposal.feedback.exclude(comment="").select_related("resident__user", "kiosk").order_by("-created_at"),
        "feedback_note": "Not a representative poll: use it to see themes, not to count votes.",
    }


# ---------------------------------------------------------------- updates and impacts

class StatusUpdateCreateView(EditorMixin, View):
    """Post an update. It appears in the proposal summary and notifies followers."""
    def post(self, request, pk):
        p = self.get_proposal(pk)
        form = StatusUpdateForm(request.POST)
        if form.is_valid():
            upd = form.save(commit=False)
            upd.proposal, upd.author = p, request.user
            upd.save()
            notify_followers(p, Notification.Kind.UPDATE, update=upd)
            alerts.proposal_event(p, "update", f"{upd.title}: {upd.summary}", update=upd)
            messages.success(request, "Update posted to residents who follow this proposal.")
        else:
            messages.error(request, "Add a title and a summary for the update.")
        return redirect("admin_console:proposal_edit", pk=p.pk)


class ImpactCreateView(EditorMixin, View):
    """Add a positive, neutral or negative impact to a completed proposal."""
    def post(self, request, pk):
        p = self.get_proposal(pk)
        if p.status != "completed":
            raise Http404
        form = ImpactForm(request.POST)
        if form.is_valid():
            imp = form.save(commit=False)
            imp.proposal, imp.author = p, request.user
            imp.save()
            notify_followers(p, Notification.Kind.IMPACT, impact=imp)
            alerts.proposal_event(p, "impact", f"New {imp.get_kind_display().lower()} impact: {imp.text}", impact=imp)
            messages.success(request, "Impact added. Residents see it in the Impacts tab.")
        else:
            messages.error(request, "Choose a type and describe what happened.")
        return redirect("admin_console:proposal_edit", pk=p.pk)


def notify_followers(proposal, kind, **target):
    """Only residents who follow the proposal are notified. Unique constraints prevent duplicates."""
    residents = ResidentProfile.objects.filter(follow__proposal=proposal)
    Notification.objects.bulk_create(
        [Notification(resident=r, kind=kind, proposal=proposal, **target) for r in residents],
        ignore_conflicts=True)


# ---------------------------------------------------------------- feedback moderation

class FeedbackToggleView(ModeratorMixin, View):
    """Mark helpful / used in decision / hidden. POST only; no points are awarded."""
    FIELDS = {"helpful": "marked_helpful", "used": "used_in_decision", "hide": "is_hidden"}

    def post(self, request, pk, field):
        if field not in self.FIELDS:
            raise Http404
        fb = get_object_or_404(Feedback, pk=pk, proposal__municipality=self.municipality)
        attr = self.FIELDS[field]
        setattr(fb, attr, not getattr(fb, attr))
        fb.save(update_fields=[attr, "updated_at"])
        return redirect(f"{reverse('admin_console:proposal_edit', args=[fb.proposal_id])}#feedback")


# ---------------------------------------------------------------- community posts

class CommunityPostListView(StaffMixin, ListView):
    template_name = "admin_console/community_list.html"
    context_object_name = "posts"

    def get_queryset(self):
        return (CommunityPost.objects.filter(proposal__municipality=self.municipality)
                .select_related("proposal").annotate(feedback_total=Count("proposal__feedback"))
                .order_by("-published_at"))

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        ctx["missing"] = self.proposals().filter(status="completed", community_post__isnull=True)
        return ctx


class CommunityPostFormMixin(EditorMixin):
    model = CommunityPost
    form_class = CommunityPostForm
    template_name = "admin_console/community_form.html"

    def get_context_data(self, **kw):
        ctx = super().get_context_data(**kw)
        proposal = self.proposal
        ctx["proposal"] = proposal
        ctx["feedback_total"] = proposal.feedback.filter(is_hidden=False).count()
        ctx["resident_ideas"] = proposal.feedback.filter(is_hidden=False).exclude(comment="")[:6]
        return ctx

    def form_valid(self, form):
        post = form.save(commit=False)
        post.proposal = self.proposal
        post.community_did = form.cleaned_data["community_did"]
        post.what_changed = form.cleaned_data["what_changed"]
        is_new = post.pk is None
        if is_new:
            post.author, post.published_at = self.request.user, timezone.now()
        post.save()
        form.save_m2m()
        if is_new:
            # Community stories go to everyone in the municipality who has an account.
            residents = ResidentProfile.objects.filter(municipality=self.municipality)
            Notification.objects.bulk_create(
                [Notification(resident=r, kind=Notification.Kind.COMMUNITY, proposal=post.proposal, post=post)
                 for r in residents], ignore_conflicts=True)
        messages.success(self.request, "Posted. Residents see it in the Community tab and in their notifications.")
        return redirect("admin_console:community_list")


class CommunityPostCreateView(CommunityPostFormMixin, CreateView):
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        self.proposal = get_object_or_404(Proposal, pk=kwargs["pk"], status="completed",
                                          municipality__staff__user=request.user)
        if hasattr(self.proposal, "community_post"):
            return redirect("admin_console:post_edit", pk=self.proposal.community_post.pk)  # one per proposal
        return super().dispatch(request, *args, **kwargs)

    def get_form_kwargs(self):
        kw = super().get_form_kwargs()
        kw["proposal"] = self.proposal
        return kw


class CommunityPostUpdateView(CommunityPostFormMixin, UpdateView):
    def get_queryset(self):
        return CommunityPost.objects.filter(proposal__municipality=self.municipality)

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        self.proposal = obj.proposal
        return obj


class CommunityPostDeleteView(EditorMixin, DeleteView):
    template_name = "admin_console/confirm_delete.html"

    def get_queryset(self):
        return CommunityPost.objects.filter(proposal__municipality=self.municipality)

    def get_success_url(self):
        messages.success(self.request, "Post deleted.")
        return reverse("admin_console:community_list")
