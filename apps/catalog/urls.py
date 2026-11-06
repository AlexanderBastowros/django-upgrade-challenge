from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register(r"categories", views.CategoryViewSet, basename="category")
router.register(r"tags", views.TagViewSet, basename="tag")
router.register(r"stores", views.StoreViewSet, basename="store")
router.register(r"products", views.ProductViewSet, basename="product")
router.register(r"product-images", views.ProductImageViewSet, basename="product-image")
router.register(r"product-variants", views.ProductVariantViewSet, basename="product-variant")
router.register(r"reviews", views.ReviewViewSet, basename="review")
router.register(r"questions", views.ProductQuestionViewSet, basename="question")

urlpatterns = router.urls
