from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register(r"carts", views.CartViewSet, basename="cart")
router.register(r"cart-items", views.CartItemViewSet, basename="cart-item")
router.register(r"wishlists", views.WishlistViewSet, basename="wishlist")
router.register(r"wishlist-items", views.WishlistItemViewSet, basename="wishlist-item")
router.register(r"coupons", views.CouponViewSet, basename="coupon")
router.register(r"orders", views.OrderViewSet, basename="order")
router.register(r"order-items", views.OrderItemViewSet, basename="order-item")
router.register(r"payments", views.PaymentViewSet, basename="payment")
router.register(r"shipments", views.ShipmentViewSet, basename="shipment")

urlpatterns = router.urls
