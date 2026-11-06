from django.contrib.auth import password_validation
from django.db import transaction
from rest_framework import serializers

from .models import Address, Follow, Profile, User


class UserSummarySerializer(serializers.ModelSerializer):
    """Compact user representation embedded in other resources."""

    public_name = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = ("id", "username", "public_name", "is_seller")
        read_only_fields = fields


class UserSerializer(serializers.ModelSerializer):
    public_name = serializers.CharField(read_only=True)
    followers_count = serializers.SerializerMethodField()
    following_count = serializers.SerializerMethodField()
    is_followed = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "display_name",
            "public_name",
            "is_seller",
            "avatar",
            "date_joined",
            "followers_count",
            "following_count",
            "is_followed",
        )
        read_only_fields = ("id", "date_joined", "is_seller")

    def get_followers_count(self, obj) -> int:
        annotated = getattr(obj, "followers_total", None)
        return annotated if annotated is not None else obj.follower_set.count()

    def get_following_count(self, obj) -> int:
        annotated = getattr(obj, "following_total", None)
        return annotated if annotated is not None else obj.following_set.count()

    def get_is_followed(self, obj) -> bool:
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False
        return Follow.objects.filter(follower=request.user, followee=obj).exists()


class AdminUserSerializer(UserSerializer):
    """Staff-only serializer: can create users and toggle flags."""

    password = serializers.CharField(write_only=True, required=False, style={"input_type": "password"})

    class Meta(UserSerializer.Meta):
        fields = UserSerializer.Meta.fields + (
            "email",
            "first_name",
            "last_name",
            "phone",
            "is_active",
            "is_staff",
            "email_verified",
            "password",
        )
        read_only_fields = ("id", "date_joined")
        extra_kwargs = {"is_seller": {"read_only": False}}

    def create(self, validated_data):
        password = validated_data.pop("password", None)
        user = User(**validated_data)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save()
        return user

    def update(self, instance, validated_data):
        password = validated_data.pop("password", None)
        instance = super().update(instance, validated_data)
        if password:
            instance.set_password(password)
            instance.save(update_fields=["password"])
        return instance


class MeSerializer(serializers.ModelSerializer):
    public_name = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "email",
            "first_name",
            "last_name",
            "display_name",
            "public_name",
            "phone",
            "date_of_birth",
            "is_seller",
            "email_verified",
            "avatar",
            "date_joined",
            "last_login",
        )
        read_only_fields = ("id", "username", "email_verified", "date_joined", "last_login")


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, style={"input_type": "password"})
    password_confirm = serializers.CharField(write_only=True, style={"input_type": "password"})
    accept_marketing = serializers.NullBooleanField(required=False, write_only=True)

    class Meta:
        model = User
        fields = (
            "id",
            "username",
            "email",
            "password",
            "password_confirm",
            "display_name",
            "is_seller",
            "accept_marketing",
        )
        read_only_fields = ("id",)

    def validate_email(self, value):
        value = value.lower()
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with that email already exists.")
        return value

    def validate(self, attrs):
        if attrs["password"] != attrs.pop("password_confirm"):
            raise serializers.ValidationError({"password_confirm": "Passwords do not match."})
        candidate = User(username=attrs.get("username"), email=attrs.get("email"))
        password_validation.validate_password(attrs["password"], user=candidate)
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        accept_marketing = validated_data.pop("accept_marketing", None)
        password = validated_data.pop("password")
        user = User(**validated_data)
        user.set_password(password)
        user.save()
        if accept_marketing is not None:
            Profile.objects.filter(user=user).update(marketing_opt_in=accept_marketing)
        return user


class ChangePasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True)

    def validate_old_password(self, value):
        if not self.context["request"].user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value

    def validate_new_password(self, value):
        password_validation.validate_password(value, user=self.context["request"].user)
        return value


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()


class EmailVerificationSerializer(serializers.Serializer):
    token = serializers.CharField()


class EmailVerificationTokenSerializer(serializers.Serializer):
    token = serializers.CharField(read_only=True)
    detail = serializers.CharField(read_only=True)


class TemporaryPasswordSerializer(serializers.Serializer):
    temporary_password = serializers.CharField(read_only=True)


class ProfileSerializer(serializers.ModelSerializer):
    user = UserSummarySerializer(read_only=True)
    marketing_opt_in = serializers.NullBooleanField(required=False)

    class Meta:
        model = Profile
        fields = (
            "id",
            "user",
            "bio",
            "website",
            "location",
            "preferred_currency",
            "timezone",
            "marketing_opt_in",
            "social_links",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "user", "created_at", "updated_at")

    def validate_timezone(self, value):
        import pytz

        if value not in pytz.all_timezones_set:
            raise serializers.ValidationError("Unknown timezone %r." % value)
        return value

    def validate_social_links(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Must be an object of {network: url}.")
        allowed = {"twitter", "instagram", "facebook", "tiktok", "youtube", "website"}
        unknown = set(value) - allowed
        if unknown:
            raise serializers.ValidationError("Unsupported networks: %s" % ", ".join(sorted(unknown)))
        return value

    def validate(self, attrs):
        request = self.context.get("request")
        if self.instance is None and request and Profile.objects.filter(user=request.user).exists():
            raise serializers.ValidationError("You already have a profile; update it instead.")
        return attrs


class AddressSerializer(serializers.ModelSerializer):
    user = serializers.HiddenField(default=serializers.CurrentUserDefault())
    one_line = serializers.CharField(read_only=True)

    class Meta:
        model = Address
        fields = (
            "id",
            "user",
            "kind",
            "label",
            "full_name",
            "line1",
            "line2",
            "city",
            "region",
            "postal_code",
            "country",
            "phone",
            "is_default",
            "one_line",
            "created_at",
            "updated_at",
        )
        read_only_fields = ("id", "created_at", "updated_at")

    def validate_country(self, value):
        value = value.upper()
        if len(value) != 2 or not value.isalpha():
            raise serializers.ValidationError("Use a 2-letter ISO country code.")
        return value

    def _clear_other_defaults(self, user, kind, exclude_pk=None):
        qs = Address.objects.filter(user=user, kind=kind, is_default=True)
        if exclude_pk:
            qs = qs.exclude(pk=exclude_pk)
        qs.update(is_default=False)

    @transaction.atomic
    def create(self, validated_data):
        if validated_data.get("is_default"):
            self._clear_other_defaults(validated_data["user"], validated_data.get("kind", Address.Kind.SHIPPING))
        return super().create(validated_data)

    @transaction.atomic
    def update(self, instance, validated_data):
        if validated_data.get("is_default"):
            self._clear_other_defaults(instance.user, validated_data.get("kind", instance.kind), instance.pk)
        return super().update(instance, validated_data)


class FollowSerializer(serializers.ModelSerializer):
    follower = UserSummarySerializer(read_only=True)
    followee = UserSummarySerializer(read_only=True)
    followee_id = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(is_active=True), source="followee", write_only=True
    )

    class Meta:
        model = Follow
        fields = ("id", "follower", "followee", "followee_id", "notify", "created_at")
        read_only_fields = ("id", "created_at")

    def validate(self, attrs):
        request = self.context["request"]
        followee = attrs.get("followee")
        if self.instance is not None:
            if followee is not None and followee != self.instance.followee:
                raise serializers.ValidationError({"followee_id": "Cannot change who a follow points at."})
            return attrs
        if followee == request.user:
            raise serializers.ValidationError({"followee_id": "You cannot follow yourself."})
        if Follow.objects.filter(follower=request.user, followee=followee).exists():
            raise serializers.ValidationError({"followee_id": "You already follow this user."})
        return attrs

