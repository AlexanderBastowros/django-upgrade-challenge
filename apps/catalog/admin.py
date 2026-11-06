from django.contrib import admin

from .models import Category, Product, ProductImage, ProductQuestion, ProductVariant, Review, Store, Tag


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "parent", "is_active", "position")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "status", "is_verified", "created_at")
    list_filter = ("status", "is_verified")
    search_fields = ("name", "owner__username")


class ProductImageInline(admin.TabularInline):
    model = ProductImage
    extra = 0


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 0


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("title", "store", "price", "stock", "status", "is_featured", "is_deleted")
    list_filter = ("status", "is_featured", "is_deleted")
    search_fields = ("title", "sku")
    inlines = (ProductImageInline, ProductVariantInline)

    def get_queryset(self, request):
        return Product.all_objects.select_related("store")


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ("product", "author", "rating", "is_verified_purchase", "is_deleted")


@admin.register(ProductQuestion)
class ProductQuestionAdmin(admin.ModelAdmin):
    list_display = ("product", "author", "is_public", "answered_at")
