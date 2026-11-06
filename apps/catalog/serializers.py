from decimal import Decimal

from django.conf import settings
from django.db import transaction
from rest_framework import serializers

from apps.accounts.serializers import UserSummarySerializer
from apps.core.utils import share_url

from .models import Category, Product, ProductImage, ProductQuestion, ProductVariant, Review, Store, Tag


class CategorySerializer(serializers.ModelSerializer):
    parent_id = serializers.PrimaryKeyRelatedField(
        queryset=Category.objects.all(), source="parent", allow_null=True, required=False
    )
    path = serializers.SerializerMethodField()
    product_count = serializers.IntegerField(read_only=True, required=False)

    class Meta:
        model = Category
        fields = (
            "id",
            "parent_id",
            "name",
            "slug",
            "description",
            "is_active",
            "position",
            "path",
            "product_count",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")
        extra_kwargs = {"slug": {"required": False}}

    def get_path(self, obj) -> str:
        return " / ".join([c.name for c in obj.ancestors()] + [obj.name])

    def validate_parent_id(self, value):
        node = value
        while node is not None and self.instance is not None:
            if node.pk == self.instance.pk:
                raise serializers.ValidationError("A category cannot be its own ancestor.")
            node = node.parent
        return value


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ("id", "name", "slug")
        read_only_fields = ("id",)
        extra_kwargs = {"slug": {"required": False}}


class StoreSerializer(serializers.ModelSerializer):
    owner = UserSummarySerializer(read_only=True)
    product_count = serializers.IntegerField(read_only=True, required=False)

    class Meta:
        model = Store
        fields = (
            "id",
            "owner",
            "name",
            "slug",
            "description",
            "status",
            "support_email",
            "logo",
            "return_policy",
            "is_verified",
            "product_count",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "owner", "status", "is_verified", "created_at", "updated_at")
        extra_kwargs = {"slug": {"required": False}}

    def validate(self, attrs):
        request = self.context["request"]
        if self.instance is None and not (request.user.is_seller or request.user.is_staff):
            raise serializers.ValidationError("Only seller accounts can open a store.")
        return attrs


class StoreStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=Store.Status.choices)
    reason = serializers.CharField(required=False, allow_blank=True)


class StoreStatsSerializer(serializers.Serializer):
    product_count = serializers.IntegerField()
    active_product_count = serializers.IntegerField()
    order_count = serializers.IntegerField()
    gross_revenue = serializers.DecimalField(max_digits=14, decimal_places=2)
    average_rating = serializers.FloatField(allow_null=True)
    review_count = serializers.IntegerField()


class ProductImageSerializer(serializers.ModelSerializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())

    class Meta:
        model = ProductImage
        fields = ("id", "product", "image", "thumbnail", "alt_text", "position", "is_primary", "created_at")
        read_only_fields = ("id", "thumbnail", "created_at")

    def validate_product(self, product):
        request = self.context["request"]
        if not request.user.is_staff and product.store.owner_id != request.user.id:
            raise serializers.ValidationError("You can only add images to your own products.")
        if self.instance is None:
            limit = settings.MARKETPLACE["MAX_IMAGES_PER_PRODUCT"]
            if product.images.count() >= limit:
                raise serializers.ValidationError("A product may have at most %d images." % limit)
        return product

    def validate_image(self, image):
        if image.size > 5 * 1024 * 1024:
            raise serializers.ValidationError("Images must be 5MB or smaller.")
        return image


class ProductImageUpdateSerializer(ProductImageSerializer):
    class Meta(ProductImageSerializer.Meta):
        read_only_fields = ("id", "product", "image", "thumbnail", "created_at")


class ProductVariantSerializer(serializers.ModelSerializer):
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())
    price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True)
    price_delta = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=-10000.0, max_value=10000.0, required=False
    )

    class Meta:
        model = ProductVariant
        fields = ("id", "product", "name", "sku", "price_delta", "price", "stock", "attributes", "is_active")
        read_only_fields = ("id",)

    def validate_product(self, product):
        request = self.context["request"]
        if not request.user.is_staff and product.store.owner_id != request.user.id:
            raise serializers.ValidationError("You can only add variants to your own products.")
        return product

    def validate(self, attrs):
        product = attrs.get("product") or getattr(self.instance, "product", None)
        delta = attrs.get("price_delta", getattr(self.instance, "price_delta", Decimal("0")))
        if product is not None and product.price + delta < 0:
            raise serializers.ValidationError({"price_delta": "Variant price cannot be negative."})
        return attrs


class ProductListSerializer(serializers.ModelSerializer):
    store = serializers.SlugRelatedField(slug_field="slug", read_only=True)
    category = serializers.SlugRelatedField(slug_field="slug", read_only=True)
    primary_image = serializers.SerializerMethodField()
    rating_avg = serializers.FloatField(read_only=True, allow_null=True)
    rating_count = serializers.IntegerField(read_only=True)
    is_on_sale = serializers.BooleanField(read_only=True)

    class Meta:
        model = Product
        fields = (
            "id",
            "store",
            "category",
            "title",
            "slug",
            "price",
            "compare_at_price",
            "currency",
            "is_on_sale",
            "status",
            "is_featured",
            "stock",
            "primary_image",
            "rating_avg",
            "rating_count",
            "published_at",
        )

    def get_primary_image(self, obj) -> str:
        images = list(obj.images.all())
        if not images:
            return ""
        primary = next((i for i in images if i.is_primary), images[0])
        request = self.context.get("request")
        url = primary.image.url
        return request.build_absolute_uri(url) if request else url


class ProductSerializer(serializers.ModelSerializer):
    store_id = serializers.PrimaryKeyRelatedField(queryset=Store.objects.all(), source="store")
    category_id = serializers.PrimaryKeyRelatedField(
        queryset=Category.objects.filter(is_active=True), source="category", allow_null=True, required=False
    )
    tags = serializers.SlugRelatedField(slug_field="name", queryset=Tag.objects.all(), many=True, required=False)
    images = ProductImageSerializer(many=True, read_only=True)
    variants = ProductVariantSerializer(many=True, read_only=True)
    price = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0.0)
    is_on_sale = serializers.BooleanField(read_only=True)
    discount_percent = serializers.DecimalField(max_digits=5, decimal_places=1, read_only=True)
    in_stock = serializers.BooleanField(read_only=True)
    share_url = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = (
            "id",
            "store_id",
            "category_id",
            "tags",
            "title",
            "slug",
            "description",
            "sku",
            "price",
            "compare_at_price",
            "currency",
            "is_on_sale",
            "discount_percent",
            "stock",
            "in_stock",
            "status",
            "is_featured",
            "weight_grams",
            "images",
            "variants",
            "share_url",
            "published_at",
            "created_at",
            "updated_at",
        )
        # slug is generated from the title (unique per store) and never changes
        read_only_fields = ("id", "slug", "status", "published_at", "created_at", "updated_at")

    def get_share_url(self, obj) -> str:
        return share_url("/p/%s/%s" % (obj.store.slug, obj.slug), obj.title)

    def validate_store_id(self, store):
        request = self.context["request"]
        if not request.user.is_staff and store.owner_id != request.user.id:
            raise serializers.ValidationError("You can only list products in your own store.")
        if store.status in (Store.Status.SUSPENDED, Store.Status.CLOSED):
            raise serializers.ValidationError("This store cannot list products.")
        return store

    def validate_is_featured(self, value):
        request = self.context["request"]
        if value and not request.user.is_staff:
            raise serializers.ValidationError("Only staff can feature products.")
        return value

    def validate(self, attrs):
        price = attrs.get("price", getattr(self.instance, "price", None))
        compare = attrs.get("compare_at_price", getattr(self.instance, "compare_at_price", None))
        if compare is not None and price is not None and compare < price:
            raise serializers.ValidationError({"compare_at_price": "Must be greater than or equal to price."})
        if self.instance is not None and "store" in attrs and attrs["store"] != self.instance.store:
            raise serializers.ValidationError({"store_id": "Products cannot be moved between stores."})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        tags = validated_data.pop("tags", [])
        product = Product.objects.create(**validated_data)
        product.tags.set(tags)
        return product

    @transaction.atomic
    def update(self, instance, validated_data):
        tags = validated_data.pop("tags", None)
        instance = super().update(instance, validated_data)
        if tags is not None:
            instance.tags.set(tags)
        return instance


class ProductStatusSerializer(serializers.Serializer):
    detail = serializers.CharField()
    status = serializers.ChoiceField(choices=Product.Status.choices)


class ProductStockAdjustSerializer(serializers.Serializer):
    delta = serializers.IntegerField(help_text="Positive to restock, negative to remove stock.")
    reason = serializers.CharField(required=False, allow_blank=True, max_length=200)


class ReviewSerializer(serializers.ModelSerializer):
    author = UserSummarySerializer(read_only=True)
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())

    class Meta:
        model = Review
        fields = (
            "id",
            "product",
            "author",
            "rating",
            "title",
            "body",
            "is_verified_purchase",
            "helpful_count",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "author", "is_verified_purchase", "helpful_count", "created_at", "updated_at")

    def validate_product(self, product):
        if self.instance is not None and product != self.instance.product:
            raise serializers.ValidationError("Cannot move a review to another product.")
        request = self.context["request"]
        if product.store.owner_id == request.user.id:
            raise serializers.ValidationError("You cannot review your own product.")
        return product

    def validate(self, attrs):
        request = self.context["request"]
        product = attrs.get("product")
        if self.instance is None and Review.objects.filter(product=product, author=request.user).exists():
            raise serializers.ValidationError({"product": "You have already reviewed this product."})
        return attrs


class ProductQuestionSerializer(serializers.ModelSerializer):
    author = UserSummarySerializer(read_only=True)
    answered_by = UserSummarySerializer(read_only=True)
    product = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all())
    is_answered = serializers.BooleanField(read_only=True)

    class Meta:
        model = ProductQuestion
        fields = (
            "id",
            "product",
            "author",
            "question",
            "answer",
            "answered_by",
            "answered_at",
            "is_answered",
            "is_public",
            "created_at",
        )
        read_only_fields = ("id", "author", "answer", "answered_by", "answered_at", "created_at")


class AnswerSerializer(serializers.Serializer):
    answer = serializers.CharField(max_length=4000)
