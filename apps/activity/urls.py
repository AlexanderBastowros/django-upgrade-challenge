from rest_framework.routers import DefaultRouter

from . import views

router = DefaultRouter()
router.register(r"actions", views.UserActionViewSet, basename="action")
router.register(r"notifications", views.NotificationViewSet, basename="notification")
router.register(r"saved-searches", views.SavedSearchViewSet, basename="saved-search")

urlpatterns = router.urls
