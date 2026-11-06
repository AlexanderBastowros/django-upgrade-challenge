from django.contrib.contenttypes.models import ContentType
from django.utils.encoding import force_text

from .models import Notification, UserAction


def client_ip(request):
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")


def record_action(user, verb, target=None, request=None, metadata=None):
    valid = {choice for choice, _ in UserAction.Verb.choices}
    if verb not in valid:
        metadata = dict(metadata or {}, original_verb=verb)
        verb = UserAction.Verb.CUSTOM
    action = UserAction(user=user, verb=verb, metadata=metadata or {})
    if target is not None:
        action.content_type = ContentType.objects.get_for_model(target, for_concrete_model=False)
        action.object_id = force_text(target.pk) if target.pk is not None else ""
        action.target_repr = force_text(target)[:200]
    if request is not None:
        action.ip_address = client_ip(request)
        action.user_agent = request.META.get("HTTP_USER_AGENT", "")[:300]
    action.save()
    return action


def notify(recipient, title, body="", level=Notification.Level.INFO, link="", actor=None):
    return Notification.objects.create(
        recipient=recipient, title=title[:140], body=body, level=level, link=link, actor=actor
    )
