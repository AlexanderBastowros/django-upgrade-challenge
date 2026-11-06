from django.conf.urls import url
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView, TokenVerifyView

from . import views

router = DefaultRouter()
router.register(r"users", views.UserViewSet, basename="user")
router.register(r"profiles", views.ProfileViewSet, basename="profile")
router.register(r"addresses", views.AddressViewSet, basename="address")
router.register(r"follows", views.FollowViewSet, basename="follow")

auth_urlpatterns = [
    url(r"^register/$", views.RegisterView.as_view(), name="auth-register"),
    url(r"^token/$", TokenObtainPairView.as_view(), name="auth-token"),
    url(r"^token/refresh/$", TokenRefreshView.as_view(), name="auth-token-refresh"),
    url(r"^token/verify/$", TokenVerifyView.as_view(), name="auth-token-verify"),
    url(r"^logout/$", views.LogoutView.as_view(), name="auth-logout"),
    url(r"^me/$", views.MeView.as_view(), name="auth-me"),
    url(r"^password/change/$", views.ChangePasswordView.as_view(), name="auth-password-change"),
    url(r"^email/verify/request/$", views.RequestEmailVerificationView.as_view(), name="auth-email-verify-request"),
    url(r"^email/verify/confirm/$", views.ConfirmEmailVerificationView.as_view(), name="auth-email-verify-confirm"),
]

urlpatterns = router.urls
