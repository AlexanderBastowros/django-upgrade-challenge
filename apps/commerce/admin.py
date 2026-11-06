from django.contrib import admin

from .models import Cart, CartItem, Coupon, Order, OrderItem, Payment, Shipment, Wishlist, WishlistItem


class CartItemInline(admin.TabularInline):
    model = CartItem
    extra = 0


@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "name", "is_active", "updated_at")
    inlines = (CartItemInline,)


class WishlistItemInline(admin.TabularInline):
    model = WishlistItem
    extra = 0


@admin.register(Wishlist)
class WishlistAdmin(admin.ModelAdmin):
    list_display = ("id", "user", "name", "is_public")
    inlines = (WishlistItemInline,)


@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = ("code", "store", "discount_type", "value", "used_count", "max_uses", "is_active")
    list_filter = ("discount_type", "is_active")


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ("number", "user", "status", "total", "placed_at")
    list_filter = ("status",)
    search_fields = ("number", "user__username")
    inlines = (OrderItemInline, PaymentInline)
    date_hierarchy = "created_at"


@admin.register(Shipment)
class ShipmentAdmin(admin.ModelAdmin):
    list_display = ("order", "carrier", "tracking_number", "status", "shipped_at")
