from rest_framework import serializers

from .models import Notification, SavedSearch, UserAction


class UserActionSerializer(serializers.ModelSerializer):
    user = serializers.HiddenField(default=serializers.CurrentUserDefault())
    username = serializers.CharField(source="user.username", read_only=True)
    target_type = serializers.SerializerMethodField()
    target_type_input = serializers.ChoiceField(
        choices=("product", "store", "user", "category", "order"),
        write_only=True,
        required=False,
        help_text="Model the action refers to (with object_id).",
    )

    class Meta:
        model = UserAction
        fields = (
            "id",
            "user",
            "username",
            "verb",
            "target_type",
            "target_type_input",
            "object_id",
            "target_repr",
            "metadata",
            "ip_address",
            "user_agent",
            "created_at",
        )
        read_only_fields = ("id", "target_repr", "ip_address", "user_agent", "created_at")

    def get_target_type(self, obj) -> str:
        return obj.content_type.model if obj.content_type_id else ""

    def validate_verb(self, verb):
        if self.instance is None and verb not in UserAction.CLIENT_VERBS:
            raise serializers.ValidationError(
                "Clients may only record: %s." % ", ".join(str(v) for v in UserAction.CLIENT_VERBS)
            )
        if self.instance is not None and verb != self.instance.verb:
            raise serializers.ValidationError("The verb of an existing action cannot change.")
        return verb

    def validate_metadata(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Metadata must be an object.")
        if len(str(value)) > 4000:
            raise serializers.ValidationError("Metadata is too large.")
        return value

    def validate(self, attrs):
        model_name = attrs.pop("target_type_input", None)
        object_id = attrs.get("object_id")
        if model_name and not object_id:
            raise serializers.ValidationError({"object_id": "Required when target_type_input is given."})
        if model_name:
            from django.apps import apps

            app_label = {"product": "catalog", "store": "catalog", "category": "catalog", "user": "accounts", "order": "commerce"}[model_name]
            model = apps.get_model(app_label, model_name)
            target = model._default_manager.filter(pk=object_id).first()
            if target is None:
                raise serializers.ValidationError({"object_id": "Target does not exist."})
            from django.contrib.contenttypes.models import ContentType

            attrs["content_type"] = ContentType.objects.get_for_model(model)
            attrs["target_repr"] = str(target)[:200]
        return attrs


class ActionSummaryRowSerializer(serializers.Serializer):
    verb = serializers.CharField()
    count = serializers.IntegerField()


class NotificationSerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source="actor.public_name", read_only=True, default=None)

    class Meta:
        model = Notification
        fields = (
            "id",
            "recipient",
            "actor",
            "actor_name",
            "level",
            "title",
            "body",
            "link",
            "is_read",
            "read_at",
            "created_at",
        )
        read_only_fields = ("id", "actor", "read_at", "created_at")


class NotificationUpdateSerializer(NotificationSerializer):
    class Meta(NotificationSerializer.Meta):
        read_only_fields = ("id", "recipient", "actor", "level", "title", "body", "link", "read_at", "created_at")


class UnreadCountSerializer(serializers.Serializer):
    unread = serializers.IntegerField()


class SavedSearchSerializer(serializers.ModelSerializer):
    user = serializers.HiddenField(default=serializers.CurrentUserDefault())

    ALLOWED_FILTERS = {"category", "store", "tag", "min_price", "max_price", "in_stock", "on_sale", "ordering"}

    class Meta:
        model = SavedSearch
        fields = ("id", "user", "name", "query", "filters", "notify_frequency", "last_run_at", "created_at", "updated_at")
        read_only_fields = ("id", "last_run_at", "created_at", "updated_at")

    def validate_filters(self, value):
        if not isinstance(value, dict):
            raise serializers.ValidationError("Filters must be an object.")
        unknown = set(value) - self.ALLOWED_FILTERS
        if unknown:
            raise serializers.ValidationError("Unsupported filters: %s" % ", ".join(sorted(unknown)))
        return value
