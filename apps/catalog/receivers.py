import logging

from django.dispatch import receiver

from apps.core.signals import product_status_changed

logger = logging.getLogger("marketplace.catalog")


@receiver(product_status_changed, dispatch_uid="catalog_log_status_change")
def log_status_change(sender, product, old_status, new_status, **kwargs):
    logger.info("Product %s status %s -> %s", product.pk, old_status, new_status)
