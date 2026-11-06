import django_filters

from .models import Category, Product, ProductQuestion, ProductVariant, Review, Store


class CategoryFilter(django_filters.FilterSet):
    root = django_filters.BooleanFilter(field_name="parent", lookup_expr="isnull", label="Only root categories")

    class Meta:
        model = Category
        fields = ("parent", "is_active")


class StoreFilter(django_filters.FilterSet):
    owner = django_filters.NumberFilter(field_name="owner_id")

    class Meta:
        model = Store
        fields = ("status", "is_verified")


class ProductFilter(django_filters.FilterSet):
    min_price = django_filters.NumberFilter(field_name="price", lookup_expr="gte")
    max_price = django_filters.NumberFilter(field_name="price", lookup_expr="lte")
    category = django_filters.CharFilter(field_name="category__slug")
    store = django_filters.CharFilter(field_name="store__slug")
    tag = django_filters.CharFilter(field_name="tags__name", distinct=True)
    in_stock = django_filters.BooleanFilter(method="filter_in_stock")
    on_sale = django_filters.BooleanFilter(method="filter_on_sale")

    class Meta:
        model = Product
        fields = ("status", "is_featured", "currency")

    def filter_in_stock(self, queryset, name, value):
        return queryset.filter(stock__gt=0) if value else queryset.filter(stock=0)

    def filter_on_sale(self, queryset, name, value):
        from django.db.models import F

        if value:
            return queryset.filter(compare_at_price__gt=F("price"))
        return queryset.exclude(compare_at_price__gt=F("price"))


class ProductVariantFilter(django_filters.FilterSet):
    class Meta:
        model = ProductVariant
        fields = ("product", "is_active")


class ReviewFilter(django_filters.FilterSet):
    min_rating = django_filters.NumberFilter(field_name="rating", lookup_expr="gte")

    class Meta:
        model = Review
        fields = ("product", "author", "rating", "is_verified_purchase")


class ProductQuestionFilter(django_filters.FilterSet):
    answered = django_filters.BooleanFilter(method="filter_answered")

    class Meta:
        model = ProductQuestion
        fields = ("product", "author")

    def filter_answered(self, queryset, name, value):
        return queryset.exclude(answer="") if value else queryset.filter(answer="")
