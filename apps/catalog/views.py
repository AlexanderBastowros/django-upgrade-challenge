from django.db import transaction
from django.db.models import Avg, Count, F, Q, Sum
from django.utils import timezone
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import parsers, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.core.exceptions import BusinessRuleViolation
from apps.core.mixins import ActionLoggingMixin, MultiSerializerMixin, SwaggerFakeViewMixin
from apps.core.permissions import IsAdminOrReadOnly, IsOwnerOrReadOnly
from apps.core.utils import make_thumbnail

from .filters import (
    CategoryFilter,
    ProductFilter,
    ProductQuestionFilter,
    ProductVariantFilter,
    ReviewFilter,
    StoreFilter,
)
from .models import Category, Product, ProductImage, ProductQuestion, ProductVariant, Review, Store, Tag
from .serializers import (
    AnswerSerializer,
    CategorySerializer,
    ProductImageSerializer,
    ProductImageUpdateSerializer,
    ProductListSerializer,
    ProductQuestionSerializer,
    ProductSerializer,
    ProductStatusSerializer,
    ProductStockAdjustSerializer,
    ProductVariantSerializer,
    ReviewSerializer,
    StoreSerializer,
    StoreStatsSerializer,
    StoreStatusSerializer,
    TagSerializer,
)

READ_OR_OWNER = (permissions.IsAuthenticatedOrReadOnly, IsOwnerOrReadOnly)


@extend_schema(tags=["catalog"])
class CategoryViewSet(ActionLoggingMixin, viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = (IsAdminOrReadOnly,)
    filterset_class = CategoryFilter
    search_fields = ("name", "description")
    ordering_fields = ("position", "name", "product_count")

    def get_queryset(self):
        qs = Category.objects.select_related("parent").annotate(
            product_count=Count("products", filter=Q(products__is_deleted=False), distinct=True)
        ).order_by("position", "name")
        if not (self.request.user and self.request.user.is_staff):
            qs = qs.filter(is_active=True)
        return qs

    @extend_schema(responses=CategorySerializer(many=True))
    @action(detail=True, methods=["get"], pagination_class=None)
    def children(self, request, pk=None):
        category = self.get_object()
        serializer = self.get_serializer(self.get_queryset().filter(parent=category), many=True)
        return Response(serializer.data)


@extend_schema(tags=["catalog"])
class TagViewSet(ActionLoggingMixin, viewsets.ModelViewSet):
    queryset = Tag.objects.all()
    serializer_class = TagSerializer
    permission_classes = (IsAdminOrReadOnly,)
    search_fields = ("name",)
    ordering_fields = ("name",)


@extend_schema(tags=["catalog"])
class StoreViewSet(ActionLoggingMixin, viewsets.ModelViewSet):
    queryset = Store.objects.all()
    serializer_class = StoreSerializer
    permission_classes = READ_OR_OWNER
    filterset_class = StoreFilter
    search_fields = ("name", "description")
    ordering_fields = ("name", "created_at", "product_count")
    lookup_value_regex = r"\d+"

    def get_queryset(self):
        qs = Store.objects.select_related("owner").annotate(
            product_count=Count("products", filter=Q(products__is_deleted=False), distinct=True)
        ).order_by("name")
        user = self.request.user
        if user and user.is_staff:
            return qs
        if user and user.is_authenticated:
            return qs.filter(Q(status=Store.Status.ACTIVE) | Q(owner=user))
        return qs.filter(status=Store.Status.ACTIVE)

    def perform_create(self, serializer):
        serializer.save(owner=self.request.user)
        self._log("created", serializer.instance)

    def perform_destroy(self, instance):
        if instance.products.filter(order_items__isnull=False).exists():
            raise BusinessRuleViolation("Stores with order history must be closed, not deleted.", "store_has_orders")
        super().perform_destroy(instance)

    @extend_schema(request=StoreStatusSerializer, responses=StoreSerializer)
    @action(detail=True, methods=["post"], url_path="set-status", permission_classes=[permissions.IsAdminUser])
    def set_status(self, request, pk=None):
        store = self.get_object()
        serializer = StoreStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        store.status = serializer.validated_data["status"]
        store.save(update_fields=["status", "updated_at"])
        self._log("status_changed", store)
        return Response(StoreSerializer(store, context=self.get_serializer_context()).data)

    @extend_schema(request=None, responses=StoreSerializer)
    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        store = self.get_object()
        if store.owner != request.user and not request.user.is_staff:
            raise PermissionDenied("Only the owner can close this store.")
        with transaction.atomic():
            store.status = Store.Status.CLOSED
            store.save(update_fields=["status", "updated_at"])
            store.products.filter(status=Product.Status.ACTIVE).update(status=Product.Status.ARCHIVED)
        self._log("closed", store)
        return Response(StoreSerializer(store, context=self.get_serializer_context()).data)

    @extend_schema(responses=StoreStatsSerializer)
    @action(detail=True, methods=["get"])
    def stats(self, request, pk=None):
        from apps.commerce.models import Order, OrderItem

        store = self.get_object()
        if store.owner != request.user and not request.user.is_staff:
            raise PermissionDenied("Only the owner can view store stats.")
        products = Product.objects.filter(store=store)
        items = OrderItem.objects.filter(product__store=store).exclude(order__status=Order.Status.CANCELLED)
        revenue = items.aggregate(total=Sum(F("unit_price") * F("quantity")))["total"] or 0
        reviews = Review.objects.filter(product__store=store)
        data = {
            "product_count": products.count(),
            "active_product_count": products.filter(status=Product.Status.ACTIVE).count(),
            "order_count": items.values("order_id").distinct().count(),
            "gross_revenue": revenue,
            "average_rating": reviews.aggregate(avg=Avg("rating"))["avg"],
            "review_count": reviews.count(),
        }
        return Response(StoreStatsSerializer(data).data)


@extend_schema_view(
    list=extend_schema(summary="Browse products"),
    retrieve=extend_schema(summary="Product detail"),
    destroy=extend_schema(summary="Soft-delete a product"),
)
@extend_schema(tags=["catalog"])
class ProductViewSet(MultiSerializerMixin, ActionLoggingMixin, viewsets.ModelViewSet):
    queryset = Product.objects.all()
    serializer_class = ProductSerializer
    serializer_classes = {"list": ProductListSerializer}
    permission_classes = READ_OR_OWNER
    owner_field = "store.owner"
    filterset_class = ProductFilter
    search_fields = ("title", "description", "sku", "tags__name")
    ordering_fields = ("price", "created_at", "published_at", "title", "rating_avg", "stock")

    def get_queryset(self):
        return (
            Product.objects.visible_to(self.request.user)
            .select_related("store", "category")
            .prefetch_related("tags", "images", "variants")
            .with_rating()
            .order_by("-created_at", "-id")
        )

    def perform_destroy(self, instance):
        self._log("deleted", instance)
        instance.soft_delete()

    def _transition(self, request, new_status, allowed_from):
        product = self.get_object()
        self.check_object_permissions(request, product)
        if product.status not in allowed_from:
            raise BusinessRuleViolation(
                "Cannot move product from %s to %s." % (product.status, new_status), "invalid_transition"
            )
        if new_status == Product.Status.ACTIVE and not product.store.is_open:
            raise BusinessRuleViolation("The store must be active to publish products.", "store_not_active")
        product.status = new_status
        if new_status == Product.Status.ACTIVE:
            product.published_at = timezone.now()
        product.save()
        self._log("status_changed", product)
        return Response({"detail": "Product is now %s." % new_status, "status": new_status})

    @extend_schema(request=None, responses=ProductStatusSerializer)
    @action(detail=True, methods=["post"])
    def publish(self, request, pk=None):
        return self._transition(request, Product.Status.ACTIVE, (Product.Status.DRAFT, Product.Status.ARCHIVED))

    @extend_schema(request=None, responses=ProductStatusSerializer)
    @action(detail=True, methods=["post"])
    def archive(self, request, pk=None):
        return self._transition(request, Product.Status.ARCHIVED, (Product.Status.ACTIVE, Product.Status.DRAFT))

    @extend_schema(request=ProductStockAdjustSerializer, responses=ProductSerializer)
    @action(detail=True, methods=["post"], url_path="adjust-stock")
    def adjust_stock(self, request, pk=None):
        product = self.get_object()
        self.check_object_permissions(request, product)
        serializer = ProductStockAdjustSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        delta = serializer.validated_data["delta"]
        with transaction.atomic():
            locked = Product.objects.select_for_update().get(pk=product.pk)
            if locked.stock + delta < 0:
                raise BusinessRuleViolation("Stock cannot go below zero.", "insufficient_stock")
            locked.stock = F("stock") + delta
            locked.save(update_fields=["stock", "updated_at"])
        self._log("stock_adjusted", product)
        return Response(ProductSerializer(self.get_queryset().get(pk=product.pk), context=self.get_serializer_context()).data)

    @extend_schema(responses=ProductListSerializer(many=True))
    @action(detail=True, methods=["get"], pagination_class=None)
    def related(self, request, pk=None):
        product = self.get_object()
        qs = (
            self.get_queryset()
            .filter(Q(category=product.category) | Q(tags__in=product.tags.all()))
            .exclude(pk=product.pk)
            .distinct()[:12]
        )
        return Response(ProductListSerializer(qs, many=True, context=self.get_serializer_context()).data)

    @extend_schema(responses=ProductListSerializer(many=True))
    @action(detail=False, methods=["get"])
    def featured(self, request):
        qs = self.filter_queryset(self.get_queryset().filter(is_featured=True))
        page = self.paginate_queryset(qs)
        serializer = ProductListSerializer(page, many=True, context=self.get_serializer_context())
        return self.get_paginated_response(serializer.data)


@extend_schema(tags=["catalog"])
class ProductImageViewSet(SwaggerFakeViewMixin, ActionLoggingMixin, viewsets.ModelViewSet):
    queryset = ProductImage.objects.all()
    serializer_class = ProductImageSerializer
    permission_classes = READ_OR_OWNER
    owner_field = "product.store.owner"
    parser_classes = (parsers.MultiPartParser, parsers.FormParser, parsers.JSONParser)
    filterset_fields = ("product", "is_primary")

    def get_owned_queryset(self):
        visible = Product.objects.visible_to(self.request.user)
        return ProductImage.objects.select_related("product__store").filter(product__in=visible)

    def get_serializer_class(self):
        if self.action in ("update", "partial_update"):
            return ProductImageUpdateSerializer
        return ProductImageSerializer

    def _sync_primary(self, image):
        if image.is_primary:
            ProductImage.objects.filter(product=image.product, is_primary=True).exclude(pk=image.pk).update(
                is_primary=False
            )

    def perform_create(self, serializer):
        super().perform_create(serializer)
        image = serializer.instance
        image.thumbnail.save("thumb_%s.jpg" % image.pk, make_thumbnail(image.image), save=True)
        self._sync_primary(image)

    def perform_update(self, serializer):
        super().perform_update(serializer)
        self._sync_primary(serializer.instance)


@extend_schema(tags=["catalog"])
class ProductVariantViewSet(SwaggerFakeViewMixin, ActionLoggingMixin, viewsets.ModelViewSet):
    queryset = ProductVariant.objects.all()
    serializer_class = ProductVariantSerializer
    permission_classes = READ_OR_OWNER
    owner_field = "product.store.owner"
    filterset_class = ProductVariantFilter
    search_fields = ("name", "sku")

    def get_owned_queryset(self):
        visible = Product.objects.visible_to(self.request.user)
        return ProductVariant.objects.select_related("product__store").filter(product__in=visible)


@extend_schema(tags=["catalog"])
class ReviewViewSet(SwaggerFakeViewMixin, ActionLoggingMixin, viewsets.ModelViewSet):
    queryset = Review.objects.all()
    serializer_class = ReviewSerializer
    permission_classes = READ_OR_OWNER
    owner_field = "author"
    filterset_class = ReviewFilter
    search_fields = ("title", "body")
    ordering_fields = ("created_at", "rating", "helpful_count")

    def get_owned_queryset(self):
        return Review.objects.select_related("author", "product").filter(
            product__in=Product.objects.visible_to(self.request.user)
        )

    def perform_create(self, serializer):
        from apps.commerce.models import OrderItem

        product = serializer.validated_data["product"]
        verified = OrderItem.objects.filter(
            order__user=self.request.user, product=product, order__status__in=("paid", "shipped", "delivered")
        ).exists()
        serializer.save(author=self.request.user, is_verified_purchase=verified)
        self._log("reviewed", product)

    def perform_destroy(self, instance):
        self._log("deleted", instance)
        instance.soft_delete()

    @extend_schema(request=None, responses=ReviewSerializer)
    @action(detail=True, methods=["post"], permission_classes=[permissions.IsAuthenticated])
    def helpful(self, request, pk=None):
        review = self.get_object()
        if review.author_id == request.user.id:
            raise BusinessRuleViolation("You cannot mark your own review as helpful.", "own_review")
        Review.objects.filter(pk=review.pk).update(helpful_count=F("helpful_count") + 1)
        review.refresh_from_db()
        return Response(self.get_serializer(review).data)


@extend_schema(tags=["catalog"])
class ProductQuestionViewSet(SwaggerFakeViewMixin, ActionLoggingMixin, viewsets.ModelViewSet):
    queryset = ProductQuestion.objects.all()
    serializer_class = ProductQuestionSerializer
    permission_classes = READ_OR_OWNER
    owner_field = "author"
    filterset_class = ProductQuestionFilter
    search_fields = ("question", "answer")

    def get_owned_queryset(self):
        user = self.request.user
        qs = ProductQuestion.objects.select_related("author", "answered_by", "product__store").filter(
            product__in=Product.objects.visible_to(user)
        )
        if user.is_authenticated:
            return qs.filter(Q(is_public=True) | Q(author=user) | Q(product__store__owner=user))
        return qs.filter(is_public=True)

    def perform_create(self, serializer):
        serializer.save(author=self.request.user)
        self._log("asked", serializer.instance)

    @extend_schema(request=AnswerSerializer, responses=ProductQuestionSerializer)
    @action(detail=True, methods=["post"], permission_classes=[permissions.IsAuthenticated])
    def answer(self, request, pk=None):
        question = self.get_object()
        if question.product.store.owner_id != request.user.id and not request.user.is_staff:
            raise PermissionDenied("Only the store owner can answer questions.")
        serializer = AnswerSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        question.answer = serializer.validated_data["answer"]
        question.answered_by = request.user
        question.answered_at = timezone.now()
        question.save(update_fields=["answer", "answered_by", "answered_at", "updated_at"])
        self._log("answered", question)
        return Response(self.get_serializer(question).data)
