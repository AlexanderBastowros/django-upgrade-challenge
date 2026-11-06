import django_filters

from .models import Address, Follow, User


class UserFilter(django_filters.FilterSet):
    joined_after = django_filters.DateTimeFilter(field_name="date_joined", lookup_expr="gte")
    joined_before = django_filters.DateTimeFilter(field_name="date_joined", lookup_expr="lte")
    min_followers = django_filters.NumberFilter(field_name="followers_total", lookup_expr="gte")

    class Meta:
        model = User
        fields = ("is_seller", "email_verified")


class AddressFilter(django_filters.FilterSet):
    class Meta:
        model = Address
        fields = ("kind", "country", "is_default")


class FollowFilter(django_filters.FilterSet):
    followee = django_filters.NumberFilter(field_name="followee_id")

    class Meta:
        model = Follow
        fields = ("notify",)
