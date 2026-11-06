from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.utils.translation import ugettext_lazy as _

from apps.core.models import TimeStampedModel


class UserAction(models.Model):
    """Append-mostly audit/analytics log of what users do."""

    class Verb(models.TextChoices):
        CREATED = "created", _("Created")
        UPDATED = "updated", _("Updated")
        DELETED = "deleted", _("Deleted")
        VIEWED = "viewed", _("Viewed")
        SEARCHED = "searched", _("Searched")
        CLICKED = "clicked", _("Clicked")
        SHARED = "shared", _("Shared")
        FOLLOWED = "followed", _("Followed")
        UNFOLLOWED = "unfollowed", _("Unfollowed")
        REVIEWED = "reviewed", _("Reviewed")
        ASKED = "asked", _("Asked a question")
        ANSWERED = "answered", _("Answered a question")
        STATUS_CHANGED = "status_changed", _("Changed status")
        STOCK_ADJUSTED = "stock_adjusted", _("Adjusted stock")
        CHECKED_OUT = "checked_out", _("Checked out")
        PAID = "paid", _("Paid")
        CANCELLED = "cancelled", _("Cancelled")
        REFUNDED = "refunded", _("Refunded")
        CLOSED = "closed", _("Closed")
        SHIPMENT_PENDING = "shipment_pending", _("Shipment created")
        SHIPMENT_IN_TRANSIT = "shipment_in_transit", _("Shipment in transit")
        SHIPMENT_DELIVERED = "shipment_delivered", _("Shipment delivered")
        SHIPMENT_RETURNED = "shipment_returned", _("Shipment returned")
        LOGGED_IN = "logged_in", _("Logged in")
        CUSTOM = "custom", _("Custom")

    CLIENT_VERBS = (Verb.VIEWED, Verb.SEARCHED, Verb.CLICKED, Verb.SHARED, Verb.CUSTOM)

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="actions")
    verb = models.CharField(max_length=32, choices=Verb.choices, db_index=True)
    content_type = models.ForeignKey(ContentType, null=True, blank=True, on_delete=models.SET_NULL)
    object_id = models.CharField(max_length=64, blank=True)
    target = GenericForeignKey("content_type", "object_id")
    target_repr = models.CharField(max_length=200, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=300, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at", "-id")
        index_together = [("user", "verb"), ("content_type", "object_id")]

    def __str__(self):
        return "%s %s %s" % (self.user_id, self.verb, self.target_repr)


class Notification(TimeStampedModel):
    class Level(models.TextChoices):
        INFO = "info", _("Info")
        SUCCESS = "success", _("Success")
        WARNING = "warning", _("Warning")
        ERROR = "error", _("Error")

    recipient = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    level = models.CharField(max_length=10, choices=Level.choices, default=Level.INFO)
    title = models.CharField(max_length=140)
    body = models.TextField(blank=True)
    link = models.CharField(max_length=300, blank=True)
    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        index_together = [("recipient", "is_read")]

    def __str__(self):
        return self.title


class SavedSearch(TimeStampedModel):
    class Frequency(models.TextChoices):
        NEVER = "never", _("Never")
        DAILY = "daily", _("Daily")
        WEEKLY = "weekly", _("Weekly")

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="saved_searches")
    name = models.CharField(max_length=80)
    query = models.CharField(max_length=200, blank=True)
    filters = models.JSONField(default=dict, blank=True)
    notify_frequency = models.CharField(max_length=10, choices=Frequency.choices, default=Frequency.NEVER)
    last_run_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("name",)
        unique_together = ("user", "name")
        verbose_name_plural = "saved searches"

    def __str__(self):
        return self.name
