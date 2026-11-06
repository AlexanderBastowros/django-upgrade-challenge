import logging
import time

from django.conf import settings

logger = logging.getLogger("marketplace.requests")


class RequestTimingMiddleware:
    """Adds an ``X-Response-Time-ms`` header and logs slow requests."""

    def __init__(self, get_response):
        self.get_response = get_response
        self.threshold = settings.MARKETPLACE.get("SLOW_REQUEST_MS", 750)

    def __call__(self, request):
        started = time.monotonic()
        response = self.get_response(request)
        elapsed_ms = (time.monotonic() - started) * 1000
        response["X-Response-Time-ms"] = "%.1f" % elapsed_ms
        if elapsed_ms > self.threshold:
            logger.warning("Slow request %s %s took %.0fms", request.method, request.path, elapsed_ms)
        return response


class AjaxRequestMiddleware:
    """Legacy frontend sends X-Requested-With; we tag those responses so the
    old jQuery widgets know not to follow redirects."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.is_xhr = request.is_ajax()
        response = self.get_response(request)
        if request.is_xhr:
            response["X-Marketplace-Xhr"] = "1"
        return response
