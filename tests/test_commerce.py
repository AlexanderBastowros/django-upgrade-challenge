from decimal import Decimal

import pytest
from django.utils import timezone

from apps.activity.models import Notification
from apps.catalog.models import Product
from apps.commerce.models import Cart, CartItem, Coupon, Order, Payment
from apps.commerce import services

from .factories import CartFactory, CouponFactory, ProductFactory, VariantFactory, WishlistFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def cart(user):
    return CartFactory(user=user)


class TestCarts:
    def test_current_creates_cart(self, client_user, user):
        resp = client_user.get("/api/v1/carts/current/")
        assert resp.status_code == 200
        assert Cart.objects.get(user=user, is_active=True).pk == resp.data["id"]

    def test_crud_and_single_active(self, client_user, cart):
        resp = client_user.post("/api/v1/carts/", {"name": "Gifts"})
        assert resp.status_code == 201
        cart.refresh_from_db()
        assert cart.is_active is False
        assert client_user.patch("/api/v1/carts/%s/" % cart.pk, {"is_active": True}).status_code == 200
        assert Cart.objects.get(pk=resp.data["id"]).is_active is False
        assert client_user.get("/api/v1/carts/", {"is_active": "true"}).data["count"] == 1
        assert client_user.delete("/api/v1/carts/%s/" % resp.data["id"]).status_code == 204

    def test_private(self, client_other, cart):
        assert client_other.get("/api/v1/carts/%s/" % cart.pk).status_code == 404


class TestCartItems:
    def test_add_merge_update_delete(self, client_user, cart, product):
        resp = client_user.post("/api/v1/cart-items/", {"cart": cart.pk, "product": product.pk, "quantity": 2})
        assert resp.status_code == 201, resp.data
        assert Decimal(resp.data["line_total"]) == Decimal("25.00")
        merged = client_user.post("/api/v1/cart-items/", {"cart": cart.pk, "product": product.pk, "quantity": 1})
        assert merged.status_code == 200 and merged.data["quantity"] == 3
        pk = resp.data["id"]
        assert client_user.patch("/api/v1/cart-items/%s/" % pk, {"quantity": 5}).data["quantity"] == 5
        assert Decimal(client_user.get("/api/v1/carts/%s/" % cart.pk).data["subtotal"]) == Decimal("62.50")
        assert client_user.delete("/api/v1/cart-items/%s/" % pk).status_code == 204

    def test_stock_and_ownership(self, client_user, client_other, cart, product):
        assert client_user.post("/api/v1/cart-items/", {"cart": cart.pk, "product": product.pk, "quantity": 99}).status_code == 400
        assert client_other.post("/api/v1/cart-items/", {"cart": cart.pk, "product": product.pk}).status_code == 400

    def test_variant_must_match_product(self, client_user, cart, product, store):
        other_variant = VariantFactory(product=ProductFactory(store=store))
        resp = client_user.post("/api/v1/cart-items/", {"cart": cart.pk, "product": product.pk, "variant": other_variant.pk})
        assert resp.status_code == 400 and "variant" in resp.data

    def test_unpublished_products_rejected(self, client_user, cart, store):
        draft = ProductFactory(store=store, status=Product.Status.DRAFT)
        assert client_user.post("/api/v1/cart-items/", {"cart": cart.pk, "product": draft.pk}).status_code == 400

    def test_clear(self, client_user, cart, product):
        CartItem.objects.create(cart=cart, product=product, quantity=1)
        assert client_user.post("/api/v1/carts/%s/clear/" % cart.pk).data["count"] == 1


class TestCheckout:
    def test_checkout_creates_order_and_reserves_stock(self, client_user, cart, product, address):
        CartItem.objects.create(cart=cart, product=product, quantity=2)
        resp = client_user.post(
            "/api/v1/carts/%s/checkout/" % cart.pk, {"shipping_address_id": address.pk, "gift_wrap": True}
        )
        assert resp.status_code == 201, resp.data
        assert resp.data["number"].startswith("MP-")
        assert Decimal(resp.data["subtotal"]) == Decimal("25.00")
        assert Decimal(resp.data["shipping_total"]) == Decimal("6.99")
        assert Decimal(resp.data["total"]) == Decimal("31.99")
        assert resp.data["shipping_address"]["city"] == "London"
        assert resp.data["gift_wrap"] is True
        product.refresh_from_db()
        assert product.stock == 8
        assert not cart.items.exists()

    def test_empty_cart(self, client_user, cart):
        resp = client_user.post("/api/v1/carts/%s/checkout/" % cart.pk, {})
        assert resp.status_code == 409 and resp.data["code"] == "empty_cart"

    def test_checkout_with_coupon(self, client_user, cart, product):
        CouponFactory(code="TENOFF", value="10")
        CartItem.objects.create(cart=cart, product=product, quantity=8)  # 100.00 -> free shipping
        resp = client_user.post("/api/v1/carts/%s/checkout/" % cart.pk, {"coupon_code": "tenoff"})
        assert resp.status_code == 201, resp.data
        assert resp.data["coupon_code"] == "TENOFF"
        assert Decimal(resp.data["discount_total"]) == Decimal("10.00")
        assert Decimal(resp.data["total"]) == Decimal("90.00")
        assert Coupon.objects.get(code="TENOFF").used_count == 1

    def test_foreign_address_rejected(self, client_other, other_user, product, address):
        cart = CartFactory(user=other_user)
        CartItem.objects.create(cart=cart, product=product, quantity=1)
        assert client_other.post("/api/v1/carts/%s/checkout/" % cart.pk, {"shipping_address_id": address.pk}).status_code == 400


class TestCoupons:
    def test_store_owner_creates_store_coupon(self, client_seller, client_user, store):
        resp = client_seller.post("/api/v1/coupons/", {"store": store.pk, "value": "15", "discount_type": "percent"})
        assert resp.status_code == 201, resp.data
        assert len(resp.data["code"]) == 12
        assert client_user.get("/api/v1/coupons/%s/" % resp.data["id"]).status_code == 404
        assert client_seller.patch("/api/v1/coupons/%s/" % resp.data["id"], {"is_active": False}).data["is_valid_now"] is False
        assert client_seller.delete("/api/v1/coupons/%s/" % resp.data["id"]).status_code == 204

    def test_validation_rules(self, client_seller, client_user, store):
        assert client_user.post("/api/v1/coupons/", {"store": store.pk, "value": "5"}).status_code == 400
        assert client_seller.post("/api/v1/coupons/", {"value": "5"}).status_code == 400
        assert client_seller.post("/api/v1/coupons/", {"store": store.pk, "value": "150"}).status_code == 400
        now = timezone.now()
        resp = client_seller.post(
            "/api/v1/coupons/",
            {"store": store.pk, "value": "5", "starts_at": now.isoformat(), "ends_at": (now - timezone.timedelta(days=1)).isoformat()},
        )
        assert resp.status_code == 400

    def test_validate_endpoint(self, client_user):
        CouponFactory(code="FIVER", discount_type="fixed", value="5", min_order_total="20")
        ok = client_user.post("/api/v1/coupons/validate/", {"code": "fiver", "subtotal": "30"})
        assert ok.data["valid"] is True and Decimal(ok.data["discount"]) == Decimal("5.00")
        low = client_user.post("/api/v1/coupons/validate/", {"code": "FIVER", "subtotal": "10"})
        assert low.data["valid"] is False
        assert client_user.post("/api/v1/coupons/validate/", {"code": "NOPE", "subtotal": "10"}).data["valid"] is False

    def test_exhausted_coupon(self, client_user):
        CouponFactory(code="ONCE", max_uses=1, used_count=1)
        assert client_user.post("/api/v1/coupons/validate/", {"code": "ONCE", "subtotal": "50"}).data["valid"] is False


class TestOrders:
    def test_create_pay_and_notify(self, client_user, user, seller, product, address, django_capture_on_commit_callbacks):
        resp = client_user.post(
            "/api/v1/orders/",
            {"items": [{"product": product.pk, "quantity": 1}], "shipping_address_id": address.pk, "notes": "Ring twice"},
        )
        assert resp.status_code == 201, resp.data
        order_id = resp.data["id"]
        assert resp.data["status"] == "pending"

        with django_capture_on_commit_callbacks(execute=True):
            paid = client_user.post("/api/v1/orders/%s/pay/" % order_id, {"method": "paypal"})
        assert paid.status_code == 201, paid.data
        assert paid.data["status"] == "succeeded"
        assert Order.objects.get(pk=order_id).status == Order.Status.PAID
        assert Notification.objects.filter(recipient=user, level="success").exists()
        assert Notification.objects.filter(recipient=seller, title__startswith="New order").exists()
        assert client_user.post("/api/v1/orders/%s/pay/" % order_id, {}).status_code == 409

    def test_cannot_buy_own_product_or_beyond_stock(self, client_seller, client_user, product):
        resp = client_seller.post("/api/v1/orders/", {"items": [{"product": product.pk, "quantity": 1}]})
        assert resp.status_code == 409 and resp.data["code"] == "own_product"
        resp = client_user.post("/api/v1/orders/", {"items": [{"product": product.pk, "quantity": 11}]})
        assert resp.status_code == 409 and resp.data["code"] == "insufficient_stock"
        product.refresh_from_db()
        assert product.stock == 10  # transaction rolled back

    def test_empty_items(self, client_user):
        assert client_user.post("/api/v1/orders/", {"items": []}).status_code == 400

    def test_update_only_while_pending(self, client_user, user, product):
        order = services.create_order(user, [(product, None, 1)])
        assert client_user.patch("/api/v1/orders/%s/" % order.pk, {"notes": "Leave at door", "gift_wrap": None}).status_code == 200
        services.pay_order(order, user)
        assert client_user.patch("/api/v1/orders/%s/" % order.pk, {"notes": "Too late"}).status_code == 400

    def test_cancel_restores_stock_and_refunds(self, client_user, user, product):
        order = services.create_order(user, [(product, None, 3)])
        services.pay_order(order, user)
        resp = client_user.post("/api/v1/orders/%s/cancel/" % order.pk, {"reason": "Changed mind"})
        assert resp.data["status"] == "cancelled"
        product.refresh_from_db()
        assert product.stock == 10
        assert Payment.objects.get(order=order).status == Payment.Status.REFUNDED
        assert client_user.post("/api/v1/orders/%s/cancel/" % order.pk).status_code == 409

    def test_delete_pending_only(self, client_user, user, product):
        order = services.create_order(user, [(product, None, 1)])
        assert client_user.delete("/api/v1/orders/%s/" % order.pk).status_code == 204
        product.refresh_from_db()
        assert product.stock == 10
        paid = services.create_order(user, [(product, None, 1)])
        services.pay_order(paid, user)
        assert client_user.delete("/api/v1/orders/%s/" % paid.pk).status_code == 409

    def test_orders_private_staff_sees_all(self, client_other, client_staff, user, product):
        order = services.create_order(user, [(product, None, 1)])
        assert client_other.get("/api/v1/orders/%s/" % order.pk).status_code == 404
        assert client_staff.get("/api/v1/orders/").data["count"] == 1

    def test_filter_by_status(self, client_user, user, product):
        services.create_order(user, [(product, None, 1)])
        services.pay_order(services.create_order(user, [(product, None, 1)]), user)
        assert client_user.get("/api/v1/orders/", {"status": "paid"}).data["count"] == 1


class TestOrderItems:
    def test_edit_pending_order_lines(self, client_user, user, store, product):
        order = services.create_order(user, [(product, None, 1)])
        other = ProductFactory(store=store, price="5.00", stock=4)
        resp = client_user.post("/api/v1/order-items/", {"order": order.pk, "product": other.pk, "quantity": 2})
        assert resp.status_code == 201, resp.data
        order.refresh_from_db()
        assert order.subtotal == Decimal("22.50")
        other.refresh_from_db()
        assert other.stock == 2

        line = resp.data["id"]
        assert client_user.patch("/api/v1/order-items/%s/" % line, {"quantity": 4}).status_code == 200
        other.refresh_from_db()
        assert other.stock == 0
        assert client_user.patch("/api/v1/order-items/%s/" % line, {"quantity": 5}).status_code == 409

        assert client_user.delete("/api/v1/order-items/%s/" % line).status_code == 204
        order.refresh_from_db()
        other.refresh_from_db()
        assert order.subtotal == Decimal("12.50") and other.stock == 4

    def test_locked_after_payment(self, client_user, user, product):
        order = services.create_order(user, [(product, None, 1)])
        services.pay_order(order, user)
        line = order.items.get()
        assert client_user.patch("/api/v1/order-items/%s/" % line.pk, {"quantity": 2}).status_code == 400
        assert client_user.delete("/api/v1/order-items/%s/" % line.pk).status_code == 409


class TestPayments:
    def test_create_and_amount_check(self, client_user, user, product):
        order = services.create_order(user, [(product, None, 1)])
        assert client_user.post("/api/v1/payments/", {"order": order.pk, "amount": "1.00"}).status_code == 409
        resp = client_user.post("/api/v1/payments/", {"order": order.pk, "method": "card"})
        assert resp.status_code == 201, resp.data
        assert client_user.get("/api/v1/payments/").data["count"] == 1

    def test_admin_only_mutations_and_refund(self, client_user, client_staff, user, product):
        order = services.create_order(user, [(product, None, 1)])
        payment = services.pay_order(order, user)
        assert client_user.post("/api/v1/payments/%s/refund/" % payment.pk).status_code == 403
        assert client_user.patch("/api/v1/payments/%s/" % payment.pk, {"failure_reason": "x"}).status_code == 403
        assert client_staff.patch("/api/v1/payments/%s/" % payment.pk, {"provider_reference": "abc"}).status_code == 200
        resp = client_staff.post("/api/v1/payments/%s/refund/" % payment.pk)
        assert resp.data["status"] == "refunded"
        assert Order.objects.get(pk=order.pk).status == Order.Status.REFUNDED
        assert client_staff.delete("/api/v1/payments/%s/" % payment.pk).status_code == 204


class TestShipments:
    def test_seller_ships_buyer_tracks(self, client_seller, client_user, client_other, user, product):
        order = services.create_order(user, [(product, None, 1)])
        assert client_seller.post("/api/v1/shipments/", {"order": order.pk, "carrier": "UPS"}).status_code == 400
        services.pay_order(order, user)
        resp = client_seller.post("/api/v1/shipments/", {"order": order.pk, "carrier": "UPS", "tracking_number": "1Z"})
        assert resp.status_code == 201, resp.data
        pk = resp.data["id"]
        assert client_other.post("/api/v1/shipments/", {"order": order.pk, "carrier": "DHL"}).status_code == 400

        assert client_seller.post("/api/v1/shipments/%s/set-status/" % pk, {"status": "in_transit"}).status_code == 200
        assert Order.objects.get(pk=order.pk).status == Order.Status.SHIPPED
        assert client_user.get("/api/v1/shipments/%s/" % pk).data["status"] == "in_transit"
        assert client_user.post("/api/v1/shipments/%s/set-status/" % pk, {"status": "delivered"}).status_code == 403
        client_seller.post("/api/v1/shipments/%s/set-status/" % pk, {"status": "delivered"})
        assert Order.objects.get(pk=order.pk).status == Order.Status.DELIVERED

        assert client_user.patch("/api/v1/shipments/%s/" % pk, {"carrier": "FedEx"}).status_code == 403
        assert client_seller.patch("/api/v1/shipments/%s/" % pk, {"carrier": "FedEx"}).data["carrier"] == "FedEx"
        assert client_seller.delete("/api/v1/shipments/%s/" % pk).status_code == 204


class TestWishlists:
    def test_crud_and_items(self, client_user, product):
        resp = client_user.post("/api/v1/wishlists/", {"name": "Birthday", "is_public": True})
        assert resp.status_code == 201
        wl = resp.data["id"]
        item = client_user.post("/api/v1/wishlist-items/", {"wishlist": wl, "product": product.pk, "priority": 1})
        assert item.status_code == 201, item.data
        assert client_user.post("/api/v1/wishlist-items/", {"wishlist": wl, "product": product.pk}).status_code == 400
        assert client_user.post("/api/v1/wishlist-items/", {"wishlist": wl, "product": product.pk, "priority": 9}).status_code == 400
        assert client_user.patch("/api/v1/wishlist-items/%s/" % item.data["id"], {"note": "blue"}).data["note"] == "blue"
        assert client_user.get("/api/v1/wishlists/%s/" % wl).data["item_count"] == 1
        assert client_user.put("/api/v1/wishlists/%s/" % wl, {"name": "Xmas"}).data["name"] == "Xmas"
        assert client_user.delete("/api/v1/wishlist-items/%s/" % item.data["id"]).status_code == 204
        assert client_user.delete("/api/v1/wishlists/%s/" % wl).status_code == 204

    def test_public_wishlists_are_read_only_for_others(self, client_other, user):
        public = WishlistFactory(user=user, is_public=True)
        private = WishlistFactory(user=user, is_public=False)
        assert client_other.get("/api/v1/wishlists/%s/" % public.pk).status_code == 200
        assert client_other.get("/api/v1/wishlists/%s/" % private.pk).status_code == 404
        assert client_other.patch("/api/v1/wishlists/%s/" % public.pk, {"name": "mine"}).status_code == 404
        assert client_other.post("/api/v1/wishlist-items/", {"wishlist": public.pk, "product": 1}).status_code == 400

    def test_move_to_cart(self, client_user, user, product, store):
        wl = WishlistFactory(user=user)
        wl.items.create(product=product)
        wl.items.create(product=ProductFactory(store=store, stock=0))
        resp = client_user.post("/api/v1/wishlists/%s/move-to-cart/" % wl.pk, {"remove_from_wishlist": True})
        assert resp.status_code == 200
        assert [i["product"] for i in resp.data["items"]] == [product.pk]
        assert not wl.items.exists()
