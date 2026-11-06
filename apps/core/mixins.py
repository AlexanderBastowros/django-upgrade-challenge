from django.db import transaction


class SwaggerFakeViewMixin:
    """Return an empty queryset while drf-spectacular introspects the view.

    Views must set ``queryset`` (used for the model) and implement
    ``get_owned_queryset`` for the real request-dependent queryset.
    """

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return self.queryset.model.objects.none()
        return self.get_owned_queryset()

    def get_owned_queryset(self):
        return super().get_queryset()


class MultiSerializerMixin:
    """Pick a serializer per action via ``serializer_classes = {action: cls}``."""

    serializer_classes = {}

    def get_serializer_class(self):
        return self.serializer_classes.get(getattr(self, "action", None), self.serializer_class)


class ActionLoggingMixin:
    """Record a :class:`apps.activity.models.UserAction` on every write.

    Set ``log_target_label`` to override the label stored for the target.
    """

    def _log(self, verb, instance):
        from apps.activity.services import record_action

        user = getattr(self.request, "user", None)
        if user is None or not user.is_authenticated:
            return
        record_action(user=user, verb=verb, target=instance, request=self.request)

    def perform_create(self, serializer):
        with transaction.atomic():
            super().perform_create(serializer)
            self._log("created", serializer.instance)

    def perform_update(self, serializer):
        with transaction.atomic():
            super().perform_update(serializer)
            self._log("updated", serializer.instance)

    def perform_destroy(self, instance):
        with transaction.atomic():
            self._log("deleted", instance)
            super().perform_destroy(instance)
