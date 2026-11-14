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
    list_display = ("name", "municipality", "ward", "postal_fsas")
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


class SmsMessageInline(admin.TabularInline):
    model = models.SmsMessage
    extra = 0
    fields = ("created_at", "direction", "body", "proposal", "status", "error")
    readonly_fields = fields
    can_delete = False
    ordering = ("-created_at",)


@admin.register(models.SmsSubscriber)
class SmsSubscriberAdmin(admin.ModelAdmin):
    list_display = ("__str__", "postal_fsa", "area", "step", "is_active", "signed_up_at")
    list_filter = ("municipality", "is_active", "step", "area", "interests")
    search_fields = ("postal_fsa",)
    filter_horizontal = ("interests",)
    readonly_fields = ("signed_up_at", "opted_out_at", "created_at", "updated_at")
    inlines = [SmsMessageInline]


@admin.register(models.SmsMessage)
class SmsMessageAdmin(admin.ModelAdmin):
    list_display = ("created_at", "subscriber", "direction", "proposal", "status")
    list_filter = ("direction", "status")
    search_fields = ("body", "twilio_sid")
    readonly_fields = ("subscriber", "direction", "body", "proposal", "twilio_sid", "status", "error", "created_at")


@admin.register(models.DeviceToken)
class DeviceTokenAdmin(admin.ModelAdmin):
    list_display = ("resident", "platform", "is_active", "updated_at")
    list_filter = ("platform", "is_active")
    readonly_fields = ("token", "created_at", "updated_at")
