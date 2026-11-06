from django.conf import settings
from django.conf.urls import include, url
from django.conf.urls.static import static
from django.contrib import admin
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView

from apps.accounts.urls import auth_urlpatterns
from apps.core.views import HealthView

api_v1_patterns = [
    url(r"^auth/", include(auth_urlpatterns)),
    url(r"^", include("apps.accounts.urls")),
    url(r"^", include("apps.catalog.urls")),
    url(r"^", include("apps.commerce.urls")),
    url(r"^", include("apps.activity.urls")),
]

urlpatterns = [
    url(r"^admin/", admin.site.urls),
    url(r"^api/health/$", HealthView.as_view(), name="health"),
    url(r"^api/v1/", include(api_v1_patterns)),
    url(r"^api/schema/$", SpectacularAPIView.as_view(), name="schema"),
    url(r"^api/docs/$", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger-ui"),
    url(r"^api/redoc/$", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
