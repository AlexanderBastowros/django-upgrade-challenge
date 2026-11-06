"""Order lifecycle. Views stay thin; everything stateful lives here."""
import uuid
from decimal import Decimal

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from apps.catalog.models import Product
from apps.core.exceptions import BusinessRuleViolation
from apps.core.signals import order_placed
from apps.core.utils import generate_order_number, money

from .models import Cart, Coupon, Order, OrderItem, Payment, Shipment

FREE_SHIPPING_THRESHOLD = Decimal("75.00")
FLAT_SHIPPING = Decimal("6.99")


def address_snapshot(address):
    if address is None:
        return {}
    return {
        "full_name": address.full_name,
        "line1": address.line1,
        "line2": address.line2,
        "city": address.city,
        "region": address.region,
        "postal_code": address.postal_code,
        "country": address.country,
        "phone": address.phone,
    }


def resolve_coupon(code, subtotal, store_ids=None):
    if not code:
        return None
    try:
        coupon = Coupon.objects.get(code__iexact=code.strip())
    except Coupon.DoesNotExist:
        raise BusinessRuleViolation("Coupon %s does not exist." % code, "coupon_invalid")
    if not coupon.is_valid_now():
        raise BusinessRuleViolation("Coupon %s is not currently valid." % coupon.code, "coupon_expired")
    if coupon.store_id and store_ids is not None and coupon.store_id not in store_ids:
        raise BusinessRuleViolation("Coupon %s is not valid for these items." % coupon.code, "coupon_scope")
    if subtotal < coupon.min_order_total:
        raise BusinessRuleViolation(
            "Order must be at least %s to use this coupon." % coupon.min_order_total, "coupon_minimum"
        )
    return coupon


def shipping_for(subtotal):
    return Decimal("0.00") if subtotal >= FREE_SHIPPING_THRESHOLD else FLAT_SHIPPING


def _reserve_stock(product, quantity):
    updated = Product.objects.filter(pk=product.pk, stock__gte=quantity).update(stock=F("stock") - quantity)
    if not updated:
        raise BusinessRuleViolation("Not enough stock for %s." % product.title, "insufficient_stock")


def _assert_purchasable(product, user):
    if product.status != Product.Status.ACTIVE or not product.store.is_open:
        raise BusinessRuleViolation("%s is not available for purchase." % product.title, "product_unavailable")
    if product.store.owner_id == user.id:
        raise BusinessRuleViolation("You cannot buy your own product.", "own_product")


@transaction.atomic
def create_order(user, lines, shipping_address=None, billing_address=None, coupon_code=None, notes="", gift_wrap=None):
    """Create an order from ``lines`` = [(product, variant, quantity), ...]."""
    if not lines:
        raise BusinessRuleViolation("An order needs at least one item.", "empty_order")

    order = Order.objects.create(
        user=user,
        shipping_address=address_snapshot(shipping_address),
        billing_address=address_snapshot(billing_address or shipping_address),
        notes=notes,
        gift_wrap=gift_wrap,
        placed_at=timezone.now(),
    )
    order.number = generate_order_number(order.pk)

    store_ids = set()
    for product, variant, quantity in lines:
        _assert_purchasable(product, user)
        _reserve_stock(product, quantity)
        store_ids.add(product.store_id)
        OrderItem.objects.create(
            order=order,
            product=product,
            variant=variant,
            title=product.title if variant is None else "%s (%s)" % (product.title, variant.name),
            unit_price=variant.price if variant is not None else product.price,
            quantity=quantity,
        )

    subtotal = money(sum((i.line_total for i in order.items.all()), Decimal("0")))
    coupon = resolve_coupon(coupon_code, subtotal, store_ids)
    if coupon is not None:
        order.coupon = coupon
        Coupon.objects.filter(pk=coupon.pk).update(used_count=F("used_count") + 1)
    order.shipping_total = shipping_for(subtotal)
    order.save()
    order.recalculate()
    return order


@transaction.atomic
def checkout_cart(cart, shipping_address=None, billing_address=None, coupon_code=None, notes="", gift_wrap=None):
    cart = Cart.objects.select_for_update().get(pk=cart.pk)
    items = list(cart.items.select_related("product__store", "variant__product"))
    if not items:
        raise BusinessRuleViolation("Your cart is empty.", "empty_cart")
    order = create_order(
        cart.user,
        [(i.product, i.variant, i.quantity) for i in items],
        shipping_address=shipping_address,
        billing_address=billing_address,
        coupon_code=coupon_code,
        notes=notes,
        gift_wrap=gift_wrap,
    )
    cart.items.all().delete()
    return order


@transaction.atomic
def cancel_order(order, reason=""):
    order = Order.objects.select_for_update().get(pk=order.pk)
    if order.status not in (Order.Status.PENDING, Order.Status.PAID):
        raise BusinessRuleViolation("Only pending or paid orders can be cancelled.", "not_cancellable")
    for item in order.items.all():
        Product.all_objects.filter(pk=item.product_id).update(stock=F("stock") + item.quantity)
    if order.status == Order.Status.PAID:
        order.payments.filter(status=Payment.Status.SUCCEEDED).update(status=Payment.Status.REFUNDED)
    order.status = Order.Status.CANCELLED
    order.cancelled_at = timezone.now()
    if reason:
        order.notes = (order.notes + "\nCancelled: " + reason).strip()
    order.save(update_fields=["status", "cancelled_at", "notes", "updated_at"])
    return order


@transaction.atomic
def pay_order(order, user, method=Payment.Method.CARD, amount=None):
    order = Order.objects.select_for_update().get(pk=order.pk)
    if order.status != Order.Status.PENDING:
        raise BusinessRuleViolation("This order is not awaiting payment.", "not_payable")
    amount = money(amount if amount is not None else order.total)
    if amount != order.total:
        raise BusinessRuleViolation("Payment amount must equal the order total (%s)." % order.total, "amount_mismatch")
    payment = Payment.objects.create(
        order=order,
        user=user,
        amount=amount,
        method=method,
        status=Payment.Status.SUCCEEDED,
        provider_reference="sim_%s" % uuid.uuid4().hex[:16],
        processed_at=timezone.now(),
    )
    order.status = Order.Status.PAID
    order.paid_at = payment.processed_at
    order.save(update_fields=["status", "paid_at", "updated_at"])
    transaction.on_commit(lambda: order_placed.send(sender=Order, order=order, user=user))
    return payment


@transaction.atomic
def refund_payment(payment):
    if payment.status != Payment.Status.SUCCEEDED:
        raise BusinessRuleViolation("Only succeeded payments can be refunded.", "not_refundable")
    payment.status = Payment.Status.REFUNDED
    payment.save(update_fields=["status", "updated_at"])
    order = payment.order
    if not order.payments.filter(status=Payment.Status.SUCCEEDED).exists():
        order.status = Order.Status.REFUNDED
        order.save(update_fields=["status", "updated_at"])
    return payment


@transaction.atomic
def mark_shipment(shipment, new_status):
    now = timezone.now()
    shipment.status = new_status
    if new_status == Shipment.Status.IN_TRANSIT and shipment.shipped_at is None:
        shipment.shipped_at = now
    if new_status == Shipment.Status.DELIVERED:
        shipment.delivered_at = now
    shipment.save()
    order = shipment.order
    if new_status == Shipment.Status.IN_TRANSIT and order.status == Order.Status.PAID:
        order.status = Order.Status.SHIPPED
        order.save(update_fields=["status", "updated_at"])
    elif new_status == Shipment.Status.DELIVERED and order.status in (Order.Status.PAID, Order.Status.SHIPPED):
        order.status = Order.Status.DELIVERED
        order.save(update_fields=["status", "updated_at"])
    return shipment
