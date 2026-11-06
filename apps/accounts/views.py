from django.core import signing
from django.db.models import Count
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import generics, mixins, permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from apps.core.mixins import ActionLoggingMixin, MultiSerializerMixin, SwaggerFakeViewMixin
from apps.core.permissions import IsOwner, IsOwnerOrReadOnly, IsSelfOrAdmin
from apps.core.serializers import DetailSerializer
from apps.core.signals import user_followed

from .filters import AddressFilter, FollowFilter, UserFilter
from .models import Address, Follow, Profile, User
from .serializers import (
    AddressSerializer,
    AdminUserSerializer,
    ChangePasswordSerializer,
    EmailVerificationSerializer,
    EmailVerificationTokenSerializer,
    FollowSerializer,
    LogoutSerializer,
    MeSerializer,
    ProfileSerializer,
    RegisterSerializer,
    TemporaryPasswordSerializer,
    UserSerializer,
    UserSummarySerializer,
)


@extend_schema(tags=["auth"])
class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = (permissions.AllowAny,)
    throttle_classes = (ScopedRateThrottle,)
    throttle_scope = "register"


@extend_schema(tags=["auth"])
class MeView(generics.RetrieveUpdateAPIView):
    serializer_class = MeSerializer

    def get_object(self):
        return self.request.user


@extend_schema(tags=["auth"])
class ChangePasswordView(generics.GenericAPIView):
    serializer_class = ChangePasswordSerializer

    @extend_schema(responses={200: DetailSerializer})
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        request.user.set_password(serializer.validated_data["new_password"])
        request.user.save(update_fields=["password"])
        return Response({"detail": "Password updated."})


@extend_schema(tags=["auth"])
class LogoutView(generics.GenericAPIView):
    """Blacklist a refresh token so it can no longer be used."""

    serializer_class = LogoutSerializer

    @extend_schema(responses={205: OpenApiResponse(description="Logged out"), 400: DetailSerializer})
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            token = RefreshToken(serializer.validated_data["refresh"])
            if str(token.get("user_id")) != str(request.user.pk):
                raise TokenError("Token does not belong to this user.")
            token.blacklist()
        except TokenError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_205_RESET_CONTENT)


@extend_schema(tags=["auth"])
class RequestEmailVerificationView(generics.GenericAPIView):
    serializer_class = EmailVerificationTokenSerializer

    @extend_schema(request=None, responses={200: EmailVerificationTokenSerializer})
    def post(self, request):
        token = request.user.make_email_verification_token()
        return Response({"token": token, "detail": "Verification token issued."})


@extend_schema(tags=["auth"])
class ConfirmEmailVerificationView(generics.GenericAPIView):
    serializer_class = EmailVerificationSerializer
    permission_classes = (permissions.AllowAny,)

    @extend_schema(responses={200: DetailSerializer, 400: DetailSerializer})
    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user = User.from_email_verification_token(serializer.validated_data["token"])
        except (signing.BadSignature, User.DoesNotExist, ValueError):
            return Response({"detail": "Invalid or expired token."}, status=status.HTTP_400_BAD_REQUEST)
        user.email_verified = True
        user.save(update_fields=["email_verified"])
        return Response({"detail": "Email verified."})


@extend_schema_view(
    list=extend_schema(summary="List users"),
    retrieve=extend_schema(summary="Retrieve a user"),
    create=extend_schema(summary="Create a user (staff only)"),
    update=extend_schema(summary="Update a user (self or staff)"),
    partial_update=extend_schema(summary="Partially update a user (self or staff)"),
    destroy=extend_schema(summary="Deactivate a user (staff only)"),
)
@extend_schema(tags=["accounts"])
class UserViewSet(MultiSerializerMixin, ActionLoggingMixin, viewsets.ModelViewSet):
    queryset = User.objects.filter(is_active=True)
    serializer_class = UserSerializer
    filterset_class = UserFilter
    search_fields = ("username", "display_name", "first_name", "last_name")
    ordering_fields = ("id", "date_joined", "username", "followers_total")
    permission_classes = (permissions.IsAuthenticated, IsSelfOrAdmin)

    def get_queryset(self):
        qs = super().get_queryset().annotate(
            followers_total=Count("follower_set", distinct=True),
            following_total=Count("following_set", distinct=True),
        )
        if self.request.user.is_staff and self.action not in ("followers", "following"):
            qs = User.objects.annotate(
                followers_total=Count("follower_set", distinct=True),
                following_total=Count("following_set", distinct=True),
            )
        return qs.order_by("id")

    def get_serializer_class(self):
        if self.request and self.request.user.is_staff and self.action not in ("followers", "following"):
            return AdminUserSerializer
        if self.action in ("followers", "following"):
            return UserSummarySerializer
        return super().get_serializer_class()

    def get_permissions(self):
        if self.action in ("create", "destroy", "reset_password"):
            return [permissions.IsAdminUser()]
        return super().get_permissions()

    def perform_destroy(self, instance):
        self._log("deleted", instance)
        instance.is_active = False
        instance.save(update_fields=["is_active"])

    def _paginated_users(self, queryset):
        page = self.paginate_queryset(queryset)
        serializer = UserSummarySerializer(page, many=True, context=self.get_serializer_context())
        return self.get_paginated_response(serializer.data)

    @extend_schema(responses=UserSummarySerializer(many=True))
    @action(detail=True, methods=["get"])
    def followers(self, request, pk=None):
        user = self.get_object()
        return self._paginated_users(User.objects.filter(following_set__followee=user, is_active=True))

    @extend_schema(responses=UserSummarySerializer(many=True))
    @action(detail=True, methods=["get"])
    def following(self, request, pk=None):
        user = self.get_object()
        return self._paginated_users(User.objects.filter(follower_set__follower=user, is_active=True))

    @extend_schema(request=None, responses={201: FollowSerializer, 409: DetailSerializer})
    @action(detail=True, methods=["post"], permission_classes=[permissions.IsAuthenticated])
    def follow(self, request, pk=None):
        followee = get_object_or_404(User, pk=pk, is_active=True)
        if followee == request.user:
            return Response({"detail": "You cannot follow yourself."}, status=status.HTTP_409_CONFLICT)
        follow, created = Follow.objects.get_or_create(follower=request.user, followee=followee)
        if created:
            user_followed.send(sender=Follow, follower=request.user, followee=followee)
            self._log("followed", followee)
        return Response(
            FollowSerializer(follow, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @extend_schema(request=None, responses={204: OpenApiResponse(description="Unfollowed")})
    @action(detail=True, methods=["post"], permission_classes=[permissions.IsAuthenticated])
    def unfollow(self, request, pk=None):
        deleted, _ = Follow.objects.filter(follower=request.user, followee_id=pk).delete()
        if deleted:
            self._log("unfollowed", get_object_or_404(User, pk=pk))
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(request=None, responses=TemporaryPasswordSerializer)
    @action(detail=True, methods=["post"], url_path="reset-password")
    def reset_password(self, request, pk=None):
        user = self.get_object()
        password = User.objects.make_random_password(length=14)
        user.set_password(password)
        user.save(update_fields=["password"])
        return Response({"temporary_password": password})


@extend_schema(tags=["accounts"])
class ProfileViewSet(SwaggerFakeViewMixin, ActionLoggingMixin, viewsets.ModelViewSet):
    """Public profiles. Every user gets one on sign-up; owners may edit theirs."""

    queryset = Profile.objects.select_related("user")
    serializer_class = ProfileSerializer
    permission_classes = (permissions.IsAuthenticated, IsOwnerOrReadOnly)
    owner_field = "user"
    filterset_fields = ("preferred_currency", "user")
    search_fields = ("bio", "location", "user__username")

    def get_owned_queryset(self):
        return Profile.objects.select_related("user").filter(user__is_active=True)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
        self._log("created", serializer.instance)

    @extend_schema(responses=ProfileSerializer)
    @action(detail=False, methods=["get"])
    def mine(self, request):
        profile, _ = Profile.objects.get_or_create(user=request.user)
        return Response(self.get_serializer(profile).data)


@extend_schema(tags=["accounts"])
class AddressViewSet(SwaggerFakeViewMixin, ActionLoggingMixin, viewsets.ModelViewSet):
    queryset = Address.objects.all()
    serializer_class = AddressSerializer
    permission_classes = (permissions.IsAuthenticated, IsOwner)
    owner_field = "user"
    filterset_class = AddressFilter
    ordering_fields = ("id", "created_at", "is_default")

    def get_owned_queryset(self):
        return Address.objects.filter(user=self.request.user)

    @extend_schema(request=None, responses=AddressSerializer)
    @action(detail=True, methods=["post"], url_path="set-default")
    def set_default(self, request, pk=None):
        address = self.get_object()
        Address.objects.filter(user=request.user, kind=address.kind, is_default=True).exclude(
            pk=address.pk
        ).update(is_default=False)
        address.is_default = True
        address.save(update_fields=["is_default", "updated_at"])
        return Response(self.get_serializer(address).data)


@extend_schema(tags=["accounts"])
class FollowViewSet(
    SwaggerFakeViewMixin,
    ActionLoggingMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Follows where the current user is the follower."""

    queryset = Follow.objects.all()
    serializer_class = FollowSerializer
    permission_classes = (permissions.IsAuthenticated, IsOwner)
    owner_field = "follower"
    filterset_class = FollowFilter

    def get_owned_queryset(self):
        return Follow.objects.select_related("follower", "followee").filter(follower=self.request.user)

    def perform_create(self, serializer):
        serializer.save(follower=self.request.user)
        user_followed.send(sender=Follow, follower=self.request.user, followee=serializer.instance.followee)
        self._log("followed", serializer.instance.followee)
