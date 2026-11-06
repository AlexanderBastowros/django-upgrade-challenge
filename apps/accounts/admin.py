from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.utils.html import format_html

from .models import Address, Follow, Profile, User


class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    inlines = (ProfileInline,)
    list_display = ("username", "email", "display_name", "is_seller", "seller_badge", "is_staff", "is_active")
    list_filter = DjangoUserAdmin.list_filter + ("is_seller", "email_verified")
    fieldsets = DjangoUserAdmin.fieldsets + (
        ("Marketplace", {"fields": ("display_name", "phone", "date_of_birth", "is_seller", "email_verified", "avatar")}),
    )
    actions = ("reset_to_temporary_password",)

    def seller_badge(self, obj):
        if obj.is_seller:
            return format_html('<span style="color:#0a0">&#10004; seller</span>')
        return "-"

    seller_badge.short_description = "Seller"

    def lookup_allowed(self, lookup, value):
        if lookup.startswith("profile__"):
            return True
        return super().lookup_allowed(lookup, value)

    def reset_to_temporary_password(self, request, queryset):
        for user in queryset:
            password = User.objects.make_random_password(length=14)
            user.set_password(password)
            user.save(update_fields=["password"])
        self.message_user(request, "Reset %d password(s)." % queryset.count(), messages.SUCCESS)

    reset_to_temporary_password.short_description = "Reset to a temporary password"


@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "kind", "city", "country", "is_default")
    list_filter = ("kind", "country")
    search_fields = ("user__username", "line1", "city", "postal_code")


@admin.register(Follow)
class FollowAdmin(admin.ModelAdmin):
    list_display = ("id", "follower", "followee", "notify", "created_at")
