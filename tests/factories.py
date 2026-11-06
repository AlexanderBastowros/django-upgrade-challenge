from decimal import Decimal

import factory
from django.contrib.auth import get_user_model

from apps.accounts.models import Address
from apps.catalog.models import Category, Product, ProductVariant, Store, Tag
from apps.commerce.models import Cart, Coupon, Wishlist

User = get_user_model()


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User
        django_get_or_create = ("username",)

    username = factory.Sequence(lambda n: "user%d" % n)
    email = factory.LazyAttribute(lambda o: "%s@example.com" % o.username)
    display_name = factory.LazyAttribute(lambda o: o.username.title())
    password = factory.PostGenerationMethodCall("set_password", "s3cret-pass!")


class SellerFactory(UserFactory):
    username = factory.Sequence(lambda n: "seller%d" % n)
    is_seller = True


class StaffFactory(UserFactory):
    username = factory.Sequence(lambda n: "staff%d" % n)
    is_staff = True


class AddressFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Address

    user = factory.SubFactory(UserFactory)
    full_name = "Ada Lovelace"
    line1 = factory.Sequence(lambda n: "%d Analytical Way" % (n + 1))
    city = "London"
    postal_code = "N1 9GU"
    country = "GB"


class CategoryFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Category

    name = factory.Sequence(lambda n: "Category %d" % n)


class TagFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Tag

    name = factory.Sequence(lambda n: "tag-%d" % n)


class StoreFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Store

    owner = factory.SubFactory(SellerFactory)
    name = factory.Sequence(lambda n: "Store %d" % n)
    status = Store.Status.ACTIVE


class ProductFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Product

    store = factory.SubFactory(StoreFactory)
    category = factory.SubFactory(CategoryFactory)
    title = factory.Sequence(lambda n: "Product %d" % n)
    price = Decimal("20.00")
    stock = 10
    status = Product.Status.ACTIVE


class VariantFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = ProductVariant

    product = factory.SubFactory(ProductFactory)
    name = factory.Sequence(lambda n: "Size %d" % n)
    sku = factory.Sequence(lambda n: "SKU-%05d" % n)
    price_delta = Decimal("5.00")
    stock = 5


class CartFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Cart

    user = factory.SubFactory(UserFactory)


class WishlistFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Wishlist

    user = factory.SubFactory(UserFactory)


class CouponFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Coupon

    created_by = factory.SubFactory(StaffFactory)
    code = factory.Sequence(lambda n: "SAVE%d" % n)
    discount_type = Coupon.DiscountType.PERCENT
    value = Decimal("10.00")
