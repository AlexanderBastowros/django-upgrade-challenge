from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import ugettext_lazy as _

from apps.catalog.models import Product, ProductVariant, Store
from apps.core.models import TimeStampedModel
from apps.core.utils import generate_coupon_code, money


class Cart(TimeStampedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="carts")
    name = models.CharField(max_length=60, default="Cart")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("-is_active", "-updated_at")
        constraints = [
            models.UniqueConstraint(fields=("user",), condition=Q(is_active=True), name="commerce_one_active_cart"),
        ]

    def __str__(self):
        return "Cart<%s:%s>" % (self.user_id, self.pk)

    @property
    def subtotal(self):
        return money(sum((item.line_total for item in self.items.all()), Decimal("0")))

    @property
    def item_count(self):
        return sum(item.quantity for item in self.items.all())


class CartItem(TimeStampedModel):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="cart_items")
    variant = models.ForeignKey(ProductVariant, null=True, blank=True, on_delete=models.CASCADE, related_name="+")
    quantity = models.PositiveIntegerField(default=1, validators=[MinValueValidator(1)])

    class Meta:
        ordering = ("id",)
        unique_together = ("cart", "product", "variant")

    def __str__(self):
        return "%sx%s" % (self.quantity, self.product_id)

    @property
    def unit_price(self):
        return self.variant.price if self.variant_id else self.product.price

    @property
    def line_total(self):
        return money(self.unit_price * self.quantity)


class Wishlist(TimeStampedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="wishlists")
    name = models.CharField(max_length=80, default="My wishlist")
    is_public = models.BooleanField(default=False)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ("-updated_at",)

    def __str__(self):
        return self.name


class WishlistItem(TimeStampedModel):
    wishlist = models.ForeignKey(Wishlist, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="wishlist_items")
    note = models.CharField(max_length=200, blank=True)
    priority = models.PositiveSmallIntegerField(default=3)

    class Meta:
        ordering = ("priority", "-created_at")
        unique_together = ("wishlist", "product")

    def __str__(self):
        return "%s in %s" % (self.product_id, self.wishlist_id)


class Coupon(TimeStampedModel):
    class DiscountType(models.TextChoices):
        PERCENT = "percent", _("Percent off")
        FIXED = "fixed", _("Fixed amount off")

    code = models.CharField(max_length=32, unique=True, blank=True)
    store = models.ForeignKey(Store, null=True, blank=True, on_delete=models.CASCADE, related_name="coupons")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="coupons")
    description = models.CharField(max_length=200, blank=True)
    discount_type = models.CharField(max_length=10, choices=DiscountType.choices, default=DiscountType.PERCENT)
    value = models.DecimalField(max_digits=10, decimal_places=2)
    min_order_total = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    starts_at = models.DateTimeField(null=True, blank=True)
    ends_at = models.DateTimeField(null=True, blank=True)
    max_uses = models.PositiveIntegerField(null=True, blank=True)
    used_count = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.CheckConstraint(check=Q(value__gt=0), name="commerce_coupon_value_gt_0"),
            models.CheckConstraint(
                check=~Q(discount_type="percent") | Q(value__lte=100), name="commerce_coupon_percent_lte_100"
            ),
        ]

    def __str__(self):
        return self.code

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = generate_coupon_code()
        self.code = self.code.upper()
        super().save(*args, **kwargs)

    def is_valid_now(self, now=None):
        now = now or timezone.now()
        if not self.is_active:
            return False
        if self.starts_at and now < self.starts_at:
            return False
        if self.ends_at and now > self.ends_at:
            return False
        if self.max_uses is not None and self.used_count >= self.max_uses:
            return False
        return True

    def discount_for(self, subtotal):
        subtotal = Decimal(subtotal)
        if subtotal < self.min_order_total:
            return Decimal("0.00")
        if self.discount_type == self.DiscountType.PERCENT:
            return money(subtotal * self.value / Decimal("100"))
        return money(min(self.value, subtotal))


class Order(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", _("Pending payment")
        PAID = "paid", _("Paid")
        SHIPPED = "shipped", _("Shipped")
        DELIVERED = "delivered", _("Delivered")
        CANCELLED = "cancelled", _("Cancelled")
        REFUNDED = "refunded", _("Refunded")

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="orders")
    number = models.CharField(max_length=32, unique=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True)
    currency = models.CharField(max_length=3, default="USD")
    shipping_address = models.JSONField(default=dict, blank=True)
    billing_address = models.JSONField(default=dict, blank=True)
    coupon = models.ForeignKey(Coupon, null=True, blank=True, on_delete=models.SET_NULL, related_name="orders")
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    discount_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    shipping_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
    notes = models.TextField(blank=True)
    gift_wrap = models.NullBooleanField()
    placed_at = models.DateTimeField(null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)

    EDITABLE_STATUSES = (Status.PENDING,)

    class Meta:
        ordering = ("-created_at",)
        index_together = [("user", "status")]
        get_latest_by = "created_at"

    def __str__(self):
        return self.number or "Order<%s>" % self.pk

    @property
    def is_editable(self):
        return self.status in self.EDITABLE_STATUSES

    def recalculate(self, save=True):
        subtotal = sum((item.line_total for item in self.items.all()), Decimal("0"))
        self.subtotal = money(subtotal)
        self.discount_total = self.coupon.discount_for(self.subtotal) if self.coupon_id else Decimal("0.00")
        self.total = money(self.subtotal - self.discount_total + self.shipping_total)
        if save:
            self.save(update_fields=["subtotal", "discount_total", "total", "updated_at"])
        return self.total


class OrderItem(TimeStampedModel):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="order_items")
    variant = models.ForeignKey(ProductVariant, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    title = models.CharField(max_length=220)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField(validators=[MinValueValidator(1)])

    class Meta:
        ordering = ("id",)

    def __str__(self):
        return "%sx %s" % (self.quantity, self.title)

    @property
    def line_total(self):
        return money(self.unit_price * self.quantity)


class Payment(TimeStampedModel):
    class Method(models.TextChoices):
        CARD = "card", _("Card")
        PAYPAL = "paypal", _("PayPal")
        BANK_TRANSFER = "bank_transfer", _("Bank transfer")
        STORE_CREDIT = "store_credit", _("Store credit")

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending")
        SUCCEEDED = "succeeded", _("Succeeded")
        FAILED = "failed", _("Failed")
        REFUNDED = "refunded", _("Refunded")

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="payments")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="payments")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    method = models.CharField(max_length=20, choices=Method.choices, default=Method.CARD)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True)
    provider_reference = models.CharField(max_length=80, blank=True)
    failure_reason = models.CharField(max_length=200, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = [models.CheckConstraint(check=Q(amount__gt=0), name="commerce_payment_amount_gt_0")]

    def __str__(self):
        return "Payment<%s %s %s>" % (self.order_id, self.amount, self.status)


class Shipment(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", _("Label created")
        IN_TRANSIT = "in_transit", _("In transit")
        DELIVERED = "delivered", _("Delivered")
        RETURNED = "returned", _("Returned")

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="shipments")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    carrier = models.CharField(max_length=40)
    tracking_number = models.CharField(max_length=80, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    shipped_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return "%s %s" % (self.carrier, self.tracking_number)
