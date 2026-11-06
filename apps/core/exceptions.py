import logging

from django.utils.encoding import force_text
from rest_framework.views import exception_handler

logger = logging.getLogger("marketplace.api")


class BusinessRuleViolation(Exception):
    """Raised by service-layer code; converted to HTTP 409 by the handler."""

    default_code = "business_rule_violation"

    def __init__(self, message, code=None):
        super().__init__(message)
        self.message = message
        self.code = code or self.default_code


def api_exception_handler(exc, context):
    from rest_framework import status
    from rest_framework.response import Response

    if isinstance(exc, BusinessRuleViolation):
        return Response(
            {"detail": force_text(exc.message), "code": exc.code},
            status=status.HTTP_409_CONFLICT,
        )

    response = exception_handler(exc, context)
    if response is not None and isinstance(response.data, dict) and "detail" in response.data:
        response.data["code"] = getattr(exc, "default_code", "error")
    elif response is None:
        logger.exception("Unhandled API exception: %s", force_text(exc))
    return response
