from django.apps import AppConfig


class CatalogConfig(AppConfig):
    name = "apps.catalog"
    label = "catalog"
    verbose_name = "Catalog"

    def ready(self):
        from . import receivers  # noqa: F401
