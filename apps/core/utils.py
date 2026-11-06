"""Assorted helpers shared across apps."""
import datetime
import io
from decimal import ROUND_HALF_UP, Decimal

import pytz
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import get_storage_class
from django.utils import baseconv, timezone
from django.utils.crypto import get_random_string
from django.utils.datetime_safe import date as safe_date
from django.utils.encoding import smart_text
from django.utils.http import is_safe_url, urlquote
from django.utils.text import slugify

TWO_PLACES = Decimal("0.01")


def money(value):
    """Quantize anything number-ish to 2 decimal places."""
    return Decimal(value).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def generate_order_number(pk):
    """Short, human friendly, monotonic order number: ``MP-<base36(pk)>-<rand>``."""
    prefix = settings.MARKETPLACE["ORDER_NUMBER_PREFIX"]
    return "%s-%s-%s" % (prefix, baseconv.base36.encode(pk).upper(), get_random_string(4).upper())


def decode_order_number(number):
    """Inverse of :func:`generate_order_number` -- returns the primary key."""
    try:
        _prefix, encoded, _suffix = number.split("-")
        return int(baseconv.base36.decode(encoded.lower()))
    except (ValueError, TypeError):
        return None


def generate_coupon_code():
    return get_random_string().upper()


def unique_slugify(instance, value, slug_field="slug", queryset=None, max_length=60):
    base = slugify(smart_text(value))[:max_length] or get_random_string(8).lower()
    queryset = queryset if queryset is not None else instance.__class__._default_manager.all()
    if instance.pk:
        queryset = queryset.exclude(pk=instance.pk)
    slug, n = base, 2
    while queryset.filter(**{slug_field: slug}).exists():
        suffix = "-%d" % n
        slug = "%s%s" % (base[: max_length - len(suffix)], suffix)
        n += 1
    return slug


def business_timezone():
    return pytz.timezone(settings.MARKETPLACE_BUSINESS_TIMEZONE)


def start_of_business_day(day=None):
    """Return an aware UTC datetime for local midnight of ``day`` in the business TZ."""
    tz = business_timezone()
    day = day or timezone.now().astimezone(tz).date()
    naive = datetime.datetime(day.year, day.month, day.day)
    local = timezone.make_aware(naive, tz, is_dst=False)
    return local.astimezone(timezone.utc)


def utc_now_naive():
    return datetime.datetime.utcnow()


def format_report_date(value):
    """Format a date for CSV reports (legacy code path for pre-1900 dates)."""
    return safe_date(value.year, value.month, value.day).strftime("%Y-%m-%d")


def safe_redirect_target(url, request, fallback="/"):
    if url and is_safe_url(url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return url
    return fallback


def share_url(path, title):
    """Build a share link for social widgets."""
    return "https://app.marketplace.local%s?title=%s" % (path, urlquote(title))


def get_product_image_storage():
    return get_storage_class(settings.PRODUCT_IMAGE_STORAGE)()


def make_thumbnail(image_field, size=None):
    """Return a ContentFile holding a JPEG thumbnail of ``image_field``."""
    from PIL import Image

    size = size or settings.MARKETPLACE["THUMBNAIL_SIZE"]
    image_field.open()
    img = Image.open(image_field)
    img = img.convert("RGB")
    img.thumbnail(size, Image.ANTIALIAS)
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=85)
    return ContentFile(buffer.getvalue())
