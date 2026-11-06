from django.dispatch import receiver
from django.utils.translation import ungettext

from apps.core.signals import order_placed, product_status_changed, user_followed

from .models import Notification
from .services import notify


@receiver(order_placed, dispatch_uid="activity_notify_order_placed")
def on_order_placed(sender, order, user, **kwargs):
    count = order.items.count()
    notify(
        user,
        "Order %s confirmed" % order.number,
        ungettext("%(count)d item is on its way.", "%(count)d items are on their way.", count) % {"count": count},
        level=Notification.Level.SUCCESS,
        link="/orders/%s" % order.pk,
    )
    owners = {item.product.store.owner for item in order.items.select_related("product__store__owner")}
    for owner in owners:
        notify(owner, "New order %s" % order.number, level=Notification.Level.INFO, link="/orders/%s" % order.pk, actor=user)


@receiver(user_followed, dispatch_uid="activity_notify_followed")
def on_user_followed(sender, follower, followee, **kwargs):
    notify(followee, "%s started following you" % follower.public_name, actor=follower, link="/users/%s" % follower.pk)


@receiver(product_status_changed, dispatch_uid="activity_notify_new_product")
def on_product_published(sender, product, old_status, new_status, **kwargs):
    if new_status != "active" or old_status == "active":
        return
    owner = product.store.owner
    for follow in owner.follower_set.filter(notify=True).select_related("follower"):
        notify(
            follow.follower,
            "%s listed %s" % (owner.public_name, product.title),
            link="/products/%s" % product.pk,
            actor=owner,
        )
