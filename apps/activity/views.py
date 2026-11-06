import csv

from django.db.models import Count
from django.http import HttpResponse
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import permissions, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.catalog.filters import ProductFilter
from apps.catalog.models import Product
from apps.catalog.serializers import ProductListSerializer
from apps.core.mixins import SwaggerFakeViewMixin
from apps.core.permissions import IsOwner
from apps.core.serializers import CountSerializer
from apps.core.utils import format_report_date

from .models import Notification, SavedSearch, UserAction
from .serializers import (
    ActionSummaryRowSerializer,
    NotificationSerializer,
    NotificationUpdateSerializer,
    SavedSearchSerializer,
    UnreadCountSerializer,
    UserActionSerializer,
)
from .services import client_ip


@extend_schema(tags=["activity"])
class UserActionViewSet(SwaggerFakeViewMixin, viewsets.ModelViewSet):
    """The current user's action log.

    Server-side writes are recorded automatically; clients may additionally
    record ``viewed``/``searched``/``clicked``/``shared``/``custom`` events.
    """

    queryset = UserAction.objects.all()
    serializer_class = UserActionSerializer
    permission_classes = (permissions.IsAuthenticated, IsOwner)
    owner_field = "user"
    filterset_fields = ("verb", "object_id")
    search_fields = ("target_repr",)
    ordering_fields = ("created_at", "verb")

    def get_owned_queryset(self):
        qs = UserAction.objects.select_related("content_type", "user")
        if self.request.user.is_staff and self.request.query_params.get("all") == "1":
            return qs
        return qs.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(
            ip_address=client_ip(self.request),
            user_agent=self.request.META.get("HTTP_USER_AGENT", "")[:300],
        )

    @extend_schema(responses=ActionSummaryRowSerializer(many=True))
    @action(detail=False, methods=["get"], pagination_class=None)
    def summary(self, request):
        rows = (
            self.filter_queryset(self.get_queryset())
            .order_by()
            .values("verb")
            .annotate(count=Count("id"))
            .order_by("-count", "verb")
        )
        return Response(ActionSummaryRowSerializer(rows, many=True).data)

    @extend_schema(responses={(200, "text/csv"): OpenApiResponse(response=OpenApiTypes.STR, description="CSV export")})
    @action(detail=False, methods=["get"])
    def export(self, request):
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="actions-%s.csv"' % format_report_date(timezone.now())
        writer = csv.writer(response)
        writer.writerow(["date", "verb", "target_type", "object_id", "target", "ip"])
        queryset = self.filter_queryset(self.get_queryset()).prefetch_related("content_type")
        for item in queryset.iterator():
            writer.writerow(
                [
                    format_report_date(item.created_at),
                    item.verb,
                    item.content_type.model if item.content_type_id else "",
                    item.object_id,
                    item.target_repr,
                    item.ip_address or "",
                ]
            )
        return response


@extend_schema(tags=["activity"])
class NotificationViewSet(SwaggerFakeViewMixin, viewsets.ModelViewSet):
    queryset = Notification.objects.all()
    serializer_class = NotificationSerializer
    permission_classes = (permissions.IsAuthenticated, IsOwner)
    owner_field = "recipient"
    filterset_fields = ("is_read", "level")
    ordering_fields = ("created_at",)

    def get_owned_queryset(self):
        return Notification.objects.select_related("actor").filter(recipient=self.request.user)

    def get_serializer_class(self):
        if self.action in ("update", "partial_update"):
            return NotificationUpdateSerializer
        return NotificationSerializer

    def get_permissions(self):
        if self.action == "create":
            return [permissions.IsAdminUser()]
        return super().get_permissions()

    def perform_create(self, serializer):
        serializer.save(actor=self.request.user)

    def perform_update(self, serializer):
        is_read = serializer.validated_data.get("is_read")
        if is_read is True and not serializer.instance.is_read:
            serializer.save(read_at=timezone.now())
        elif is_read is False:
            serializer.save(read_at=None)
        else:
            serializer.save()

    @extend_schema(request=None, responses=NotificationSerializer)
    @action(detail=True, methods=["post"], url_path="mark-read")
    def mark_read(self, request, pk=None):
        notification = self.get_object()
        if not notification.is_read:
            notification.is_read = True
            notification.read_at = timezone.now()
            notification.save(update_fields=["is_read", "read_at", "updated_at"])
        return Response(self.get_serializer(notification).data)

    @extend_schema(request=None, responses=CountSerializer)
    @action(detail=False, methods=["post"], url_path="mark-all-read")
    def mark_all_read(self, request):
        count = self.get_queryset().filter(is_read=False).update(is_read=True, read_at=timezone.now())
        return Response({"count": count, "detail": "Marked as read."})

    @extend_schema(responses=UnreadCountSerializer)
    @action(detail=False, methods=["get"], url_path="unread-count")
    def unread_count(self, request):
        return Response({"unread": self.get_queryset().filter(is_read=False).count()})


@extend_schema(tags=["activity"])
class SavedSearchViewSet(SwaggerFakeViewMixin, viewsets.ModelViewSet):
    queryset = SavedSearch.objects.all()
    serializer_class = SavedSearchSerializer
    permission_classes = (permissions.IsAuthenticated, IsOwner)
    owner_field = "user"
    filterset_fields = ("notify_frequency",)
    search_fields = ("name", "query")

    def get_owned_queryset(self):
        return SavedSearch.objects.filter(user=self.request.user)

    @extend_schema(request=None, responses=ProductListSerializer(many=True))
    @action(detail=True, methods=["post"])
    def run(self, request, pk=None):
        saved = self.get_object()
        qs = Product.objects.visible_to(request.user).select_related("store", "category").prefetch_related("images")
        qs = qs.with_rating().order_by("-published_at", "-id")
        if saved.query:
            qs = qs.filter(title__icontains=saved.query)
        filters = {k: v for k, v in saved.filters.items() if k != "ordering"}
        qs = ProductFilter(data=filters, queryset=qs).qs
        if saved.filters.get("ordering") in ("price", "-price", "published_at", "-published_at"):
            qs = qs.order_by(saved.filters["ordering"])
        saved.last_run_at = timezone.now()
        saved.save(update_fields=["last_run_at", "updated_at"])
        page = self.paginate_queryset(qs)
        serializer = ProductListSerializer(page, many=True, context=self.get_serializer_context())
        return self.get_paginated_response(serializer.data)
