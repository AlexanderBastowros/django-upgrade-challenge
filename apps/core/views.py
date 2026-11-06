from django.conf import settings
from django.db import connection
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import HealthSerializer


class HealthView(APIView):
    permission_classes = (AllowAny,)
    authentication_classes = ()

    @extend_schema(responses=HealthSerializer, tags=["meta"], summary="Liveness/readiness probe")
    def get(self, request):
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            db_ok = True
        except Exception:  # pragma: no cover - defensive
            db_ok = False
        data = {
            "status": "ok" if db_ok else "degraded",
            "version": settings.SPECTACULAR_SETTINGS["VERSION"],
            "database": db_ok,
            "server_time": timezone.now(),
        }
        return Response(HealthSerializer(data).data)
