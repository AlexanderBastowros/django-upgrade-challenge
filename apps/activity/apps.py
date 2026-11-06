from django.apps import AppConfig


class ActivityConfig(AppConfig):
    name = "apps.activity"
    label = "activity"
    verbose_name = "Activity"

    def ready(self):
        from . import receivers
