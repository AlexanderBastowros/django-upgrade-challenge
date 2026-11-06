from decimal import Decimal

from django.conf import settings
from rest_framework import serializers

from apps.accounts.models import Address
from apps.catalog.models import Product, ProductVariant, Store
from apps.catalog.serializers import ProductListSerializer

from .models import Cart, CartItem, Coupon, Order, OrderItem, Payment, Shipment, Wishlist, WishlistItem


def _validate_variant(attrs):
    product, variant = attrs.get("product"), attrs.get("variant")
    if variant is not None and product is not None and variant.product_id != product.pk:
        raise serializers.ValidationError({"variant": "Variant does not belong to this product."})
    return attrs


class CartItemSerializer(serializers.ModelSerializer):
    cart = serializers.PrimaryKeyRelatedField(queryset=Cart.objects.all())
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.published())
    variant = serializers.PrimaryKeyRelatedField(
        queryset=ProductVariant.objects.filter(is_active=True), allow_null=True, required=False
    )
    product_detail = ProductListSerializer(source="product", read_only=True)
    unit_price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    line_total = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = CartItem
        fields = (
            "id",
            "cart",
            "product",
            "variant",
            "quantity",
            "product_detail",
            "unit_price",
            "line_total",
            "created_at",
        )
        read_only_fields = ("id", "created_at")
        validators = []  # uniqueness is handled by merging quantities in the view

    def validate_cart(self, cart):
        if cart.user_id != self.context["request"].user.id:
            raise serializers.ValidationError("You can only add items to your own cart.")
        if self.instance is not None and cart != self.instance.cart:
            raise serializers.ValidationError("Items cannot be moved between carts.")
        return cart

    def validate(self, attrs):
        attrs = _validate_variant(attrs)
        product = attrs.get("product") or self.instance.product
        quantity = attrs.get("quantity", getattr(self.instance, "quantity", 1))
        if quantity > product.stock:
            raise serializers.ValidationError({"quantity": "Only %d left in stock." % product.stock})
        cart = attrs.get("cart") or self.instance.cart
        if self.instance is None and cart.items.count() >= settings.MARKETPLACE["MAX_CART_ITEMS"]:
            raise serializers.ValidationError("Your cart is full.")
        return attrs


class CartSerializer(serializers.ModelSerializer):
    items = CartItemSerializer(many=True, read_only=True)
    subtotal = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    item_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = Cart
        fields = ("id", "name", "is_active", "items", "item_count", "subtotal", "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")


class CheckoutSerializer(serializers.Serializer):
    shipping_address_id = serializers.PrimaryKeyRelatedField(queryset=Address.objects.all(), required=False)
    billing_address_id = serializers.PrimaryKeyRelatedField(queryset=Address.objects.all(), required=False)
    coupon_code = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    gift_wrap = serializers.NullBooleanField(required=False)

    def _check_address(self, address):
        if address is not None and address.user_id != self.context["request"].user.id:
            raise serializers.ValidationError("Unknown address.")
        return address

    def validate_shipping_address_id(self, value):
        return self._check_address(value)

    def validate_billing_address_id(self, value):
        return self._check_address(value)


class WishlistItemSerializer(serializers.ModelSerializer):
    wishlist = serializers.PrimaryKeyRelatedField(queryset=Wishlist.objects.all())
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())
    product_detail = ProductListSerializer(source="product", read_only=True)

    class Meta:
        model = WishlistItem
        fields = ("id", "wishlist", "product", "product_detail", "note", "priority", "created_at")
        read_only_fields = ("id", "created_at")

    def validate_wishlist(self, wishlist):
        if wishlist.user_id != self.context["request"].user.id:
            raise serializers.ValidationError("You can only add items to your own wishlists.")
        return wishlist

    def validate_priority(self, value):
        if not 1 <= value <= 5:
            raise serializers.ValidationError("Priority must be between 1 and 5.")
        return value


class WishlistSerializer(serializers.ModelSerializer):
    items = WishlistItemSerializer(many=True, read_only=True)
    owner = serializers.CharField(source="user.public_name", read_only=True)
    item_count = serializers.SerializerMethodField()

    class Meta:
        model = Wishlist
        fields = ("id", "owner", "name", "description", "is_public", "items", "item_count", "created_at", "updated_at")
        read_only_fields = ("id", "created_at", "updated_at")

    def get_item_count(self, obj) -> int:
        return len(obj.items.all())


class MoveToCartSerializer(serializers.Serializer):
    remove_from_wishlist = serializers.BooleanField(default=False)


class CouponSerializer(serializers.ModelSerializer):
    store = serializers.PrimaryKeyRelatedField(queryset=Store.objects.all(), allow_null=True, required=False)
    created_by = serializers.HiddenField(default=serializers.CurrentUserDefault())
    value = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0.01)
    is_valid_now = serializers.BooleanField(read_only=True)

    class Meta:
        model = Coupon
        fields = (
            "id",
            "code",
            "store",
            "created_by",
            "description",
            "discount_type",
            "value",
            "min_order_total",
            "starts_at",
            "ends_at",
            "max_uses",
            "used_count",
            "is_active",
            "is_valid_now",
            "created_at",
        )
        read_only_fields = ("id", "used_count", "created_at")
        extra_kwargs = {"code": {"required": False}}

    def validate_store(self, store):
        user = self.context["request"].user
        if store is None and not user.is_staff:
            raise serializers.ValidationError("Only staff can create platform-wide coupons.")
        if store is not None and store.owner_id != user.id and not user.is_staff:
            raise serializers.ValidationError("You can only create coupons for your own store.")
        return store

    def validate(self, attrs):
        if "store" not in attrs and self.instance is None and not self.context["request"].user.is_staff:
            raise serializers.ValidationError({"store": "This field is required."})
        dtype = attrs.get("discount_type", getattr(self.instance, "discount_type", Coupon.DiscountType.PERCENT))
        value = attrs.get("value", getattr(self.instance, "value", None))
        if dtype == Coupon.DiscountType.PERCENT and value is not None and value > 100:
            raise serializers.ValidationError({"value": "Percent discounts cannot exceed 100."})
        starts, ends = attrs.get("starts_at"), attrs.get("ends_at")
        if starts and ends and ends <= starts:
            raise serializers.ValidationError({"ends_at": "Must be after starts_at."})
        return attrs


class CouponValidateSerializer(serializers.Serializer):
    code = serializers.CharField()
    subtotal = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=0)


class CouponValidateResultSerializer(serializers.Serializer):
    code = serializers.CharField()
    valid = serializers.BooleanField()
    discount = serializers.DecimalField(max_digits=12, decimal_places=2)
    detail = serializers.CharField()


class OrderItemSerializer(serializers.ModelSerializer):
    order = serializers.PrimaryKeyRelatedField(queryset=Order.objects.all())
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.published())
    variant = serializers.PrimaryKeyRelatedField(
        queryset=ProductVariant.objects.filter(is_active=True), allow_null=True, required=False
    )
    line_total = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = OrderItem
        fields = ("id", "order", "product", "variant", "title", "unit_price", "quantity", "line_total", "created_at")
        read_only_fields = ("id", "title", "unit_price", "created_at")

    def validate_order(self, order):
        user = self.context["request"].user
        if order.user_id != user.id and not user.is_staff:
            raise serializers.ValidationError("Unknown order.")
        if not order.is_editable:
            raise serializers.ValidationError("Only pending orders can be modified.")
        if self.instance is not None and order != self.instance.order:
            raise serializers.ValidationError("Items cannot be moved between orders.")
        return order

    def validate(self, attrs):
        if self.instance is not None:
            if not self.instance.order.is_editable:
                raise serializers.ValidationError("Only pending orders can be modified.")
            for locked in ("product", "variant"):
                if locked in attrs and attrs[locked] != getattr(self.instance, locked):
                    raise serializers.ValidationError({locked: "Cannot change the product of an existing line."})
        return _validate_variant(attrs)


class OrderLineInputSerializer(serializers.Serializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.published())
    variant = serializers.PrimaryKeyRelatedField(
        queryset=ProductVariant.objects.filter(is_active=True), allow_null=True, required=False
    )
    quantity = serializers.IntegerField(min_value=1, max_value=999)

    def validate(self, attrs):
        return _validate_variant(attrs)


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    coupon_code = serializers.CharField(source="coupon.code", read_only=True, default=None)
    buyer = serializers.CharField(source="user.public_name", read_only=True)
    gift_wrap = serializers.NullBooleanField(required=False)

    class Meta:
        model = Order
        fields = (
            "id",
            "number",
            "buyer",
            "status",
            "currency",
            "shipping_address",
            "billing_address",
            "coupon_code",
            "items",
            "subtotal",
            "discount_total",
            "shipping_total",
            "total",
            "notes",
            "gift_wrap",
            "placed_at",
            "paid_at",
            "cancelled_at",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "id",
            "number",
            "status",
            "currency",
            "shipping_address",
            "billing_address",
            "subtotal",
            "discount_total",
            "shipping_total",
            "total",
            "placed_at",
            "paid_at",
            "cancelled_at",
            "created_at",
            "updated_at",
        )

    def validate(self, attrs):
        if self.instance is not None and not self.instance.is_editable:
            raise serializers.ValidationError("Only pending orders can be modified.")
        return attrs


class OrderCreateSerializer(serializers.Serializer):
    items = OrderLineInputSerializer(many=True)
    shipping_address_id = serializers.PrimaryKeyRelatedField(queryset=Address.objects.all(), required=False)
    billing_address_id = serializers.PrimaryKeyRelatedField(queryset=Address.objects.all(), required=False)
    coupon_code = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    gift_wrap = serializers.NullBooleanField(required=False)

    def validate_items(self, items):
        if not items:
            raise serializers.ValidationError("At least one item is required.")
        return items

    def validate_shipping_address_id(self, address):
        if address.user_id != self.context["request"].user.id:
            raise serializers.ValidationError("Unknown address.")
        return address

    def validate_billing_address_id(self, address):
        return self.validate_shipping_address_id(address)


class CancelOrderSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=500)


class PayOrderSerializer(serializers.Serializer):
    method = serializers.ChoiceField(choices=Payment.Method.choices, default=Payment.Method.CARD)


class PaymentSerializer(serializers.ModelSerializer):
    order = serializers.PrimaryKeyRelatedField(queryset=Order.objects.all())
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"), required=False)

    class Meta:
        model = Payment
        fields = (
            "id",
            "order",
            "amount",
            "method",
            "status",
            "provider_reference",
            "failure_reason",
            "processed_at",
            "created_at",
        )
        read_only_fields = ("id", "status", "provider_reference", "failure_reason", "processed_at", "created_at")

    def validate_order(self, order):
        user = self.context["request"].user
        if order.user_id != user.id and not user.is_staff:
            raise serializers.ValidationError("Unknown order.")
        return order


class PaymentAdminUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = ("id", "order", "amount", "method", "status", "provider_reference", "failure_reason", "processed_at")
        read_only_fields = ("id", "order", "amount", "method")


class ShipmentSerializer(serializers.ModelSerializer):
    order = serializers.PrimaryKeyRelatedField(queryset=Order.objects.all())
    created_by = serializers.HiddenField(default=serializers.CurrentUserDefault())

    class Meta:
        model = Shipment
        fields = (
            "id",
            "order",
            "created_by",
            "carrier",
            "tracking_number",
            "status",
            "shipped_at",
            "delivered_at",
            "created_at",
        )
        read_only_fields = ("id", "status", "shipped_at", "delivered_at", "created_at")

    def validate_order(self, order):
        user = self.context["request"].user
        if user.is_staff:
            return order
        if not order.items.filter(product__store__owner=user).exists():
            raise serializers.ValidationError("You can only ship orders containing your products.")
        if order.status not in (Order.Status.PAID, Order.Status.SHIPPED):
            raise serializers.ValidationError("Only paid orders can be shipped.")
        return order


class ShipmentStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Shipment.Status.choices)
