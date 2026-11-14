"""Django admin (at /admin/) for IT staff: create municipalities, neighbourhoods, staff accounts and sources.
Day-to-day publishing happens in the CivicSpeak admin console at the site root."""
from django.contrib import admin
from django.contrib.gis.admin import GISModelAdmin

from . import models


@admin.register(models.Municipality)
class MunicipalityAdmin(GISModelAdmin):
    list_display = ("name", "province")


@admin.register(models.Neighbourhood)
class NeighbourhoodAdmin(GISModelAdmin):
    list_display = ("name", "municipality", "ward")
    list_filter = ("municipality",)


@admin.register(models.StaffMembership)
class StaffMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "municipality", "role")
    list_filter = ("municipality", "role")


@admin.register(models.Topic)
class TopicAdmin(admin.ModelAdmin):
    list_display = ("label", "key")


@admin.register(models.Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "topic")


@admin.register(models.Source)
class SourceAdmin(admin.ModelAdmin):
    list_display = ("title", "kind", "published_on", "municipality")
    list_filter = ("kind", "municipality")
    search_fields = ("title", "url")


class PointInline(admin.TabularInline):
    model = models.ProposalPoint
    extra = 0


class StepInline(admin.TabularInline):
    model = models.TimelineStep
    extra = 0


@admin.register(models.Proposal)
class ProposalAdmin(GISModelAdmin):
    list_display = ("title", "municipality", "status", "stage", "participation_open", "is_illustrative")
    list_filter = ("municipality", "status", "stage", "is_illustrative")
    search_fields = ("title", "summary")
    inlines = [PointInline, StepInline]
    exclude = ("search",)


@admin.register(models.Feedback)
class FeedbackAdmin(admin.ModelAdmin):
    list_display = ("proposal", "choice", "channel", "marked_helpful", "used_in_decision", "is_hidden", "created_at")
    list_filter = ("choice", "channel", "is_hidden")


for m in (models.StatusUpdate, models.Impact, models.CommunityPost, models.ReserveFund,
          models.ReserveFundStatement, models.ProjectAllocation, models.Kiosk, models.ResidentProfile,
          models.Notification):
    admin.site.register(m)
