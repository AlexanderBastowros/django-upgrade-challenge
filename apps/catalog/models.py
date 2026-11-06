from decimal import Decimal

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Avg, Count, Q
from django.utils import timezone
from django.utils.translation import ugettext_lazy as _

from apps.core.models import SoftDeleteManager, SoftDeleteModel, SoftDeleteQuerySet, TimeStampedModel
from apps.core.signals import product_status_changed
from apps.core.utils import get_product_image_storage, unique_slugify


class Category(TimeStampedModel):
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="children")
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=120, unique=True, blank=True)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("position", "name")
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slugify(self, self.name)
        super().save(*args, **kwargs)

    def ancestors(self):
        node, chain = self.parent, []
        while node is not None:
            chain.append(node)
            node = node.parent
        return list(reversed(chain))


class Tag(models.Model):
    name = models.CharField(max_length=40, unique=True)
    slug = models.SlugField(max_length=50, unique=True, blank=True)

    class Meta:
        ordering = ("name",)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slugify(self, self.name, max_length=50)
        super().save(*args, **kwargs)


class Store(TimeStampedModel):
    class Status(models.TextChoices):
        PENDING = "pending", _("Pending review")
        ACTIVE = "active", _("Active")
        SUSPENDED = "suspended", _("Suspended")
        CLOSED = "closed", _("Closed")

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="stores")
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=140, unique=True, blank=True)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True)
    support_email = models.EmailField(blank=True)
    logo = models.ImageField(upload_to="stores/logos/", null=True, blank=True)
    return_policy = models.TextField(blank=True)
    is_verified = models.BooleanField(default=False)

    class Meta:
        ordering = ("name",)
        index_together = [("owner", "status")]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slugify(self, self.name)
        super().save(*args, **kwargs)

    @property
    def is_open(self):
        return self.status == self.Status.ACTIVE


class ProductQuerySet(SoftDeleteQuerySet):
    def published(self):
        return self.filter(
            status=Product.Status.ACTIVE,
            store__status=Store.Status.ACTIVE,
            is_deleted=False,
        )

    def visible_to(self, user):
        qs = self.filter(is_deleted=False)
        if user is not None and user.is_authenticated:
            if user.is_staff:
                return qs
            return qs.filter(
                Q(status=Product.Status.ACTIVE, store__status=Store.Status.ACTIVE) | Q(store__owner=user)
            )
        return qs.published()

    def with_rating(self):
        return self.annotate(
            rating_avg=Avg("reviews__rating", filter=Q(reviews__is_deleted=False)),
            rating_count=Count("reviews", filter=Q(reviews__is_deleted=False), distinct=True),
        )


class ProductManager(SoftDeleteManager.from_queryset(ProductQuerySet)):
    pass


class Product(SoftDeleteModel, TimeStampedModel):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        ACTIVE = "active", _("Active")
        ARCHIVED = "archived", _("Archived")

    store = models.ForeignKey(Store, on_delete=models.CASCADE, related_name="products")
    category = models.ForeignKey(Category, null=True, blank=True, on_delete=models.SET_NULL, related_name="products")
    tags = models.ManyToManyField(Tag, blank=True, related_name="products")
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, blank=True)
    description = models.TextField(blank=True)
    sku = models.CharField(max_length=64, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    compare_at_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=3, default="USD")
    stock = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.DRAFT, db_index=True)
    is_featured = models.BooleanField(default=False)
    weight_grams = models.PositiveIntegerField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)

    objects = ProductManager()
    all_objects = models.Manager.from_queryset(ProductQuerySet)()

    class Meta:
        ordering = ("-created_at",)
        index_together = [("store", "status"), ("category", "status")]
        unique_together = ("store", "slug")
        constraints = [
            models.CheckConstraint(check=Q(price__gte=0), name="catalog_product_price_gte_0"),
            models.CheckConstraint(
                check=Q(compare_at_price__isnull=True) | Q(compare_at_price__gte=0),
                name="catalog_product_compare_at_gte_0",
            ),
        ]

    def __str__(self):
        return self.title

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._original_status = self.__dict__.get("status")

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slugify(self, self.title, queryset=Product.all_objects.filter(store_id=self.store_id))
        if self.status == self.Status.ACTIVE and self.published_at is None:
            self.published_at = timezone.now()
        super().save(*args, **kwargs)
        if self._original_status != self.status:
            product_status_changed.send(
                sender=Product, product=self, old_status=self._original_status, new_status=self.status
            )
            self._original_status = self.__dict__.get("status")

    @property
    def is_on_sale(self):
        return bool(self.compare_at_price and self.compare_at_price > self.price)

    @property
    def discount_percent(self):
        if not self.is_on_sale:
            return Decimal("0")
        return ((self.compare_at_price - self.price) / self.compare_at_price * 100).quantize(Decimal("0.1"))

    @property
    def in_stock(self):
        return self.stock > 0


class ProductImage(TimeStampedModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="images")
    image = models.ImageField(upload_to="products/%Y/%m/", storage=get_product_image_storage)
    thumbnail = models.ImageField(
        upload_to="products/thumbs/%Y/%m/", storage=get_product_image_storage, null=True, blank=True
    )
    alt_text = models.CharField(max_length=200, blank=True)
    position = models.PositiveIntegerField(default=0)
    is_primary = models.BooleanField(default=False)

    class Meta:
        ordering = ("position", "id")

    def __str__(self):
        return "Image<%s:%s>" % (self.product_id, self.pk)


class ProductVariant(TimeStampedModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variants")
    name = models.CharField(max_length=100)
    sku = models.CharField(max_length=64, unique=True)
    price_delta = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0.00"))
    stock = models.PositiveIntegerField(default=0)
    attributes = models.JSONField(default=dict, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("product_id", "name")

    def __str__(self):
        return "%s / %s" % (self.product_id, self.name)

    @property
    def price(self):
        return self.product.price + self.price_delta


class Review(SoftDeleteModel, TimeStampedModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="reviews")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="reviews")
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    title = models.CharField(max_length=120, blank=True)
    body = models.TextField(blank=True)
    is_verified_purchase = models.BooleanField(default=False)
    helpful_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("-created_at",)
        constraints = [
            models.UniqueConstraint(
                fields=("product", "author"),
                condition=Q(is_deleted=False),
                name="catalog_review_one_per_author",
            ),
            models.CheckConstraint(check=Q(rating__gte=1) & Q(rating__lte=5), name="catalog_review_rating_range"),
        ]

    def __str__(self):
        return "Review<%s by %s: %s>" % (self.product_id, self.author_id, self.rating)


class ProductQuestion(TimeStampedModel):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="questions")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="product_questions")
    question = models.TextField(max_length=1000)
    answer = models.TextField(blank=True)
    answered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    answered_at = models.DateTimeField(null=True, blank=True)
    is_public = models.BooleanField(default=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return "Q<%s>" % self.pk

    @property
    def is_answered(self):
        return bool(self.answer)
