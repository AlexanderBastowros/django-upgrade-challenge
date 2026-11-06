from django.db import transaction
from django.db.models import F, Prefetch, Q
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.core.exceptions import BusinessRuleViolation
from apps.core.mixins import ActionLoggingMixin, SwaggerFakeViewMixin
from apps.core.permissions import IsOwner, IsOwnerOrReadOnly
from apps.core.serializers import CountSerializer

from . import services
from .filters import CouponFilter, OrderFilter, PaymentFilter, ShipmentFilter
from .models import Cart, CartItem, Coupon, Order, OrderItem, Payment, Shipment, Wishlist, WishlistItem
from .serializers import (
    CancelOrderSerializer,
    CartItemSerializer,
    CartSerializer,
    CheckoutSerializer,
    CouponSerializer,
    CouponValidateResultSerializer,
    CouponValidateSerializer,
    MoveToCartSerializer,
    OrderCreateSerializer,
    OrderItemSerializer,
    OrderSerializer,
    PaymentAdminUpdateSerializer,
    PaymentSerializer,
    PayOrderSerializer,
    ShipmentSerializer,
    ShipmentStatusSerializer,
    WishlistItemSerializer,
    WishlistSerializer,
)


def _cart_items_prefetch():
    return Prefetch(
        "items",
        queryset=CartItem.objects.select_related("product__store", "product__category", "variant__product")
        .prefetch_related("product__images"),
    )


@extend_schema(tags=["commerce"])
class CartViewSet(SwaggerFakeViewMixin, ActionLoggingMixin, viewsets.ModelViewSet):
    queryset = Cart.objects.all()
    serializer_class = CartSerializer
    permission_classes = (permissions.IsAuthenticated, IsOwner)
    owner_field = "user"
    filterset_fields = ("is_active",)

    def get_owned_queryset(self):
        return Cart.objects.filter(user=self.request.user).prefetch_related(_cart_items_prefetch())

    @transaction.atomic
    def perform_create(self, serializer):
        if serializer.validated_data.get("is_active", True):
            Cart.objects.filter(user=self.request.user, is_active=True).update(is_active=False)
        serializer.save(user=self.request.user)
        self._log("created", serializer.instance)

    @transaction.atomic
    def perform_update(self, serializer):
        if serializer.validated_data.get("is_active"):
            Cart.objects.filter(user=self.request.user, is_active=True).exclude(pk=serializer.instance.pk).update(
                is_active=False
            )
        super().perform_update(serializer)

    @extend_schema(responses=CartSerializer)
    @action(detail=False, methods=["get"])
    def current(self, request):
        cart = Cart.objects.filter(user=request.user, is_active=True).first()
        if cart is None:
            cart = Cart.objects.create(user=request.user)
        cart = self.get_queryset().get(pk=cart.pk)
        return Response(self.get_serializer(cart).data)

    @extend_schema(request=None, responses=CountSerializer)
    @action(detail=True, methods=["post"])
    def clear(self, request, pk=None):
        cart = self.get_object()
        count, _ = cart.items.all().delete()
        return Response({"count": count, "detail": "Cart cleared."})

    @extend_schema(request=CheckoutSerializer, responses={201: OrderSerializer, 409: OpenApiResponse(description="Business rule violation")})
    @action(detail=True, methods=["post"])
    def checkout(self, request, pk=None):
        cart = self.get_object()
        serializer = CheckoutSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        order = services.checkout_cart(
            cart,
            shipping_address=data.get("shipping_address_id"),
            billing_address=data.get("billing_address_id"),
            coupon_code=data.get("coupon_code"),
            notes=data.get("notes", ""),
            gift_wrap=data.get("gift_wrap"),
        )
        self._log("checked_out", order)
        return Response(OrderSerializer(order, context=self.get_serializer_context()).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["commerce"])
class CartItemViewSet(SwaggerFakeViewMixin, ActionLoggingMixin, viewsets.ModelViewSet):
    queryset = CartItem.objects.all()
    serializer_class = CartItemSerializer
    permission_classes = (permissions.IsAuthenticated, IsOwner)
    owner_field = "cart.user"
    filterset_fields = ("cart", "product")

    def get_owned_queryset(self):
        return CartItem.objects.select_related("cart", "product__store", "variant__product").filter(
            cart__user=self.request.user
        )

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        existing = CartItem.objects.filter(
            cart=data["cart"], product=data["product"], variant=data.get("variant")
        ).first()
        if existing is not None:
            existing.quantity = F("quantity") + data.get("quantity", 1)
            existing.save(update_fields=["quantity", "updated_at"])
            existing.refresh_from_db()
            self._log("updated", existing)
            return Response(self.get_serializer(existing).data, status=status.HTTP_200_OK)
        self.perform_create(serializer)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["commerce"])
class WishlistViewSet(SwaggerFakeViewMixin, ActionLoggingMixin, viewsets.ModelViewSet):
    """Own wishlists plus any wishlist other users made public (read-only)."""

    queryset = Wishlist.objects.all()
    serializer_class = WishlistSerializer
    permission_classes = (permissions.IsAuthenticated, IsOwnerOrReadOnly)
    owner_field = "user"
    filterset_fields = ("is_public",)
    search_fields = ("name", "description")

    def get_owned_queryset(self):
        qs = Wishlist.objects.select_related("user").prefetch_related(
            Prefetch("items", queryset=WishlistItem.objects.select_related("product__store", "product__category").prefetch_related("product__images"))
        )
        if self.action in ("list", "retrieve"):
            return qs.filter(Q(user=self.request.user) | Q(is_public=True))
        return qs.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
        self._log("created", serializer.instance)

    @extend_schema(request=MoveToCartSerializer, responses=CartSerializer)
    @action(detail=True, methods=["post"], url_path="move-to-cart")
    def move_to_cart(self, request, pk=None):
        wishlist = self.get_object()
        serializer = MoveToCartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        cart = Cart.objects.filter(user=request.user, is_active=True).first() or Cart.objects.create(user=request.user)
        with transaction.atomic():
            for item in wishlist.items.select_related("product__store"):
                if not item.product.in_stock or item.product.status != "active":
                    continue
                cart_item, created = CartItem.objects.get_or_create(cart=cart, product=item.product, variant=None)
                if not created:
                    cart_item.quantity = F("quantity") + 1
                    cart_item.save(update_fields=["quantity", "updated_at"])
            if serializer.validated_data["remove_from_wishlist"]:
                wishlist.items.all().delete()
        cart = Cart.objects.prefetch_related(_cart_items_prefetch()).get(pk=cart.pk)
        return Response(CartSerializer(cart, context=self.get_serializer_context()).data)


@extend_schema(tags=["commerce"])
class WishlistItemViewSet(SwaggerFakeViewMixin, ActionLoggingMixin, viewsets.ModelViewSet):
    queryset = WishlistItem.objects.all()
    serializer_class = WishlistItemSerializer
    permission_classes = (permissions.IsAuthenticated, IsOwner)
    owner_field = "wishlist.user"
    filterset_fields = ("wishlist", "product", "priority")

    def get_owned_queryset(self):
        return WishlistItem.objects.select_related("wishlist", "product__store", "product__category").filter(
            wishlist__user=self.request.user
        )


@extend_schema(tags=["commerce"])
class CouponViewSet(SwaggerFakeViewMixin, ActionLoggingMixin, viewsets.ModelViewSet):
    queryset = Coupon.objects.all()
    serializer_class = CouponSerializer
    permission_classes = (permissions.IsAuthenticated, IsOwner)
    owner_field = "created_by"
    filterset_class = CouponFilter
    search_fields = ("code", "description")

    def get_owned_queryset(self):
        if self.request.user.is_staff:
            return Coupon.objects.select_related("store")
        return Coupon.objects.select_related("store").filter(
            Q(created_by=self.request.user) | Q(store__owner=self.request.user)
        )

    @extend_schema(request=CouponValidateSerializer, responses=CouponValidateResultSerializer)
    @action(detail=False, methods=["post"])
    def validate(self, request):
        serializer = CouponValidateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        code, subtotal = serializer.validated_data["code"], serializer.validated_data["subtotal"]
        try:
            coupon = services.resolve_coupon(code, subtotal)
        except BusinessRuleViolation as exc:
            return Response({"code": code.upper(), "valid": False, "discount": "0.00", "detail": exc.message})
        return Response(
            {"code": coupon.code, "valid": True, "discount": coupon.discount_for(subtotal), "detail": "Coupon applied."}
        )


@extend_schema(tags=["commerce"])
class OrderViewSet(SwaggerFakeViewMixin, ActionLoggingMixin, viewsets.ModelViewSet):
    queryset = Order.objects.all()
    serializer_class = OrderSerializer
    permission_classes = (permissions.IsAuthenticated, IsOwner)
    owner_field = "user"
    filterset_class = OrderFilter
    search_fields = ("number", "notes")
    ordering_fields = ("created_at", "total", "placed_at")

    def get_owned_queryset(self):
        qs = Order.objects.select_related("user", "coupon").prefetch_related("items")
        if self.request.user.is_staff:
            return qs
        return qs.filter(user=self.request.user)

    @extend_schema(request=OrderCreateSerializer, responses={201: OrderSerializer})
    def create(self, request, *args, **kwargs):
        serializer = OrderCreateSerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        order = services.create_order(
            request.user,
            [(line["product"], line.get("variant"), line["quantity"]) for line in data["items"]],
            shipping_address=data.get("shipping_address_id"),
            billing_address=data.get("billing_address_id"),
            coupon_code=data.get("coupon_code"),
            notes=data.get("notes", ""),
            gift_wrap=data.get("gift_wrap"),
        )
        self._log("created", order)
        return Response(self.get_serializer(order).data, status=status.HTTP_201_CREATED)

    def perform_destroy(self, instance):
        if instance.status != Order.Status.PENDING:
            raise BusinessRuleViolation("Only pending orders can be deleted; cancel it instead.", "not_deletable")
        services.cancel_order(instance)
        super().perform_destroy(instance)

    @extend_schema(request=CancelOrderSerializer, responses=OrderSerializer)
    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        order = self.get_object()
        serializer = CancelOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        order = services.cancel_order(order, serializer.validated_data.get("reason", ""))
        self._log("cancelled", order)
        return Response(self.get_serializer(order).data)

    @extend_schema(request=PayOrderSerializer, responses={201: PaymentSerializer})
    @action(detail=True, methods=["post"])
    def pay(self, request, pk=None):
        order = self.get_object()
        serializer = PayOrderSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payment = services.pay_order(order, request.user, method=serializer.validated_data["method"])
        self._log("paid", order)
        return Response(PaymentSerializer(payment, context=self.get_serializer_context()).data, status=status.HTTP_201_CREATED)


@extend_schema(tags=["commerce"])
class OrderItemViewSet(SwaggerFakeViewMixin, ActionLoggingMixin, viewsets.ModelViewSet):
    """Line items. Writable only while the parent order is pending; totals are recalculated."""

    queryset = OrderItem.objects.all()
    serializer_class = OrderItemSerializer
    permission_classes = (permissions.IsAuthenticated, IsOwner)
    owner_field = "order.user"
    filterset_fields = ("order", "product")

    def get_owned_queryset(self):
        qs = OrderItem.objects.select_related("order", "product", "variant__product")
        if self.request.user.is_staff:
            return qs
        return qs.filter(order__user=self.request.user)

    @transaction.atomic
    def perform_create(self, serializer):
        product = serializer.validated_data["product"]
        variant = serializer.validated_data.get("variant")
        quantity = serializer.validated_data["quantity"]
        services._assert_purchasable(product, self.request.user)
        services._reserve_stock(product, quantity)
        serializer.save(
            title=product.title if variant is None else "%s (%s)" % (product.title, variant.name),
            unit_price=variant.price if variant is not None else product.price,
        )
        serializer.instance.order.recalculate()
        self._log("created", serializer.instance)

    @transaction.atomic
    def perform_update(self, serializer):
        old_quantity = serializer.instance.quantity
        new_quantity = serializer.validated_data.get("quantity", old_quantity)
        delta = new_quantity - old_quantity
        product = serializer.instance.product
        if delta > 0:
            services._reserve_stock(product, delta)
        elif delta < 0:
            type(product).all_objects.filter(pk=product.pk).update(stock=F("stock") - delta)
        serializer.save()
        serializer.instance.order.recalculate()
        self._log("updated", serializer.instance)

    @transaction.atomic
    def perform_destroy(self, instance):
        if not instance.order.is_editable:
            raise BusinessRuleViolation("Only pending orders can be modified.", "order_locked")
        order = instance.order
        type(instance.product).all_objects.filter(pk=instance.product_id).update(stock=F("stock") + instance.quantity)
        self._log("deleted", instance)
        instance.delete()
        order.recalculate()


@extend_schema(tags=["commerce"])
class PaymentViewSet(SwaggerFakeViewMixin, ActionLoggingMixin, viewsets.ModelViewSet):
    """Buyers create payments for their orders; only staff may edit or delete them."""

    queryset = Payment.objects.all()
    serializer_class = PaymentSerializer
    permission_classes = (permissions.IsAuthenticated, IsOwner)
    owner_field = "user"
    filterset_class = PaymentFilter

    def get_owned_queryset(self):
        qs = Payment.objects.select_related("order")
        if self.request.user.is_staff:
            return qs
        return qs.filter(user=self.request.user)

    def get_serializer_class(self):
        if self.action in ("update", "partial_update"):
            return PaymentAdminUpdateSerializer
        return PaymentSerializer

    def get_permissions(self):
        if self.action in ("update", "partial_update", "destroy", "refund"):
            return [permissions.IsAdminUser()]
        return super().get_permissions()

    @extend_schema(responses={201: PaymentSerializer})
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payment = services.pay_order(
            serializer.validated_data["order"],
            request.user,
            method=serializer.validated_data.get("method", Payment.Method.CARD),
            amount=serializer.validated_data.get("amount"),
        )
        self._log("paid", payment.order)
        return Response(self.get_serializer(payment).data, status=status.HTTP_201_CREATED)

    @extend_schema(request=None, responses=PaymentSerializer)
    @action(detail=True, methods=["post"])
    def refund(self, request, pk=None):
        payment = services.refund_payment(self.get_object())
        self._log("refunded", payment)
        return Response(PaymentSerializer(payment, context=self.get_serializer_context()).data)


@extend_schema(tags=["commerce"])
class ShipmentViewSet(SwaggerFakeViewMixin, ActionLoggingMixin, viewsets.ModelViewSet):
    """Sellers create shipments for orders with their products; buyers can read them."""

    queryset = Shipment.objects.all()
    serializer_class = ShipmentSerializer
    filterset_class = ShipmentFilter

    def get_owned_queryset(self):
        user = self.request.user
        qs = Shipment.objects.select_related("order", "created_by")
        if user.is_staff:
            return qs
        return qs.filter(Q(order__user=user) | Q(created_by=user)).distinct()

    def _check_shipper(self, shipment):
        user = self.request.user
        if not user.is_staff and shipment.created_by_id != user.id:
            raise PermissionDenied("Only the shipper can modify this shipment.")

    def perform_update(self, serializer):
        self._check_shipper(serializer.instance)
        super().perform_update(serializer)

    def perform_destroy(self, instance):
        self._check_shipper(instance)
        super().perform_destroy(instance)

    @extend_schema(request=ShipmentStatusSerializer, responses=ShipmentSerializer)
    @action(detail=True, methods=["post"], url_path="set-status")
    def set_status(self, request, pk=None):
        shipment = self.get_object()
        self._check_shipper(shipment)
        serializer = ShipmentStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        shipment = services.mark_shipment(shipment, serializer.validated_data["status"])
        self._log("shipment_" + shipment.status, shipment)
        return Response(self.get_serializer(shipment).data)
