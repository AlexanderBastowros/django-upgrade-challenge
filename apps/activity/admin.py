from django.contrib import admin

from .models import Notification, SavedSearch, UserAction


@admin.register(UserAction)
class UserActionAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "verb", "content_type", "object_id", "target_repr")
    list_filter = ("verb", "content_type")
    search_fields = ("user__username", "target_repr")
    date_hierarchy = "created_at"


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("recipient", "title", "level", "is_read", "created_at")
    list_filter = ("level", "is_read")


@admin.register(SavedSearch)
class SavedSearchAdmin(admin.ModelAdmin):
    list_display = ("user", "name", "query", "notify_frequency", "last_run_at")
