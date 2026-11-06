import django_filters

from .models import Coupon, Order, Payment, Shipment


class OrderFilter(django_filters.FilterSet):
    placed_after = django_filters.DateTimeFilter(field_name="placed_at", lookup_expr="gte")
    placed_before = django_filters.DateTimeFilter(field_name="placed_at", lookup_expr="lte")
    min_total = django_filters.NumberFilter(field_name="total", lookup_expr="gte")

    class Meta:
        model = Order
        fields = ("status", "currency")


class CouponFilter(django_filters.FilterSet):
    class Meta:
        model = Coupon
        fields = ("store", "discount_type", "is_active")


class PaymentFilter(django_filters.FilterSet):
    class Meta:
        model = Payment
        fields = ("order", "status", "method")


class ShipmentFilter(django_filters.FilterSet):
    class Meta:
        model = Shipment
        fields = ("order", "status", "carrier")
