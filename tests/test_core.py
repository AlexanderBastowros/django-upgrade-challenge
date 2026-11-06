import datetime
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.test import RequestFactory, TestCase, override_settings
from django.utils import timezone

from apps.catalog.models import Product
from apps.core import utils

from .factories import ProductFactory, StoreFactory


def test_order_number_roundtrip():
    number = utils.generate_order_number(123456)
    assert number.startswith("MP-")
    assert utils.decode_order_number(number) == 123456
    assert utils.decode_order_number("garbage") is None


def test_coupon_code_shape():
    code = utils.generate_coupon_code()
    assert len(code) == 12 and code.isalnum() and code == code.upper()


def test_money_rounding():
    assert utils.money("1.005") == Decimal("1.01")
    assert utils.money(Decimal("2")) == Decimal("2.00")


@override_settings(MARKETPLACE_BUSINESS_TIMEZONE="America/New_York")
def test_start_of_business_day():
    start = utils.start_of_business_day(datetime.date(2022, 1, 15))
    assert start.tzinfo is not None
    assert start.astimezone(datetime.timezone.utc).hour == 5


def test_format_report_date():
    assert utils.format_report_date(datetime.date(2021, 3, 9)) == "2021-03-09"
    assert utils.format_report_date(timezone.now()).count("-") == 2


def test_safe_redirect_target():
    request = RequestFactory().get("/", HTTP_HOST="testserver")
    assert utils.safe_redirect_target("/orders/1", request) == "/orders/1"
    assert utils.safe_redirect_target("https://evil.example.com/", request) == "/"


def test_share_url_quotes_title():
    assert utils.share_url("/p/x", "Tea & Cakes") == "https://app.marketplace.local/p/x?title=Tea%20%26%20Cakes"


def test_utc_now_naive_is_naive():
    assert utils.utc_now_naive().tzinfo is None


@pytest.mark.django_db
def test_health(api_client):
    resp = api_client.get("/api/health/")
    assert resp.status_code == 200
    assert resp.data["status"] == "ok"
    assert "X-Response-Time-ms" in resp


@pytest.mark.django_db
def test_xhr_header(api_client):
    resp = api_client.get("/api/health/", HTTP_X_REQUESTED_WITH="XMLHttpRequest")
    assert resp["X-Marketplace-Xhr"] == "1"
    assert "X-Marketplace-Xhr" not in api_client.get("/api/health/")


@pytest.mark.django_db
def test_business_rule_violation_shape(client_user):
    resp = client_user.post("/api/v1/orders/", {"items": [{"product": 999, "quantity": 1}]})
    assert resp.status_code == 400


@pytest.mark.django_db
def test_seed_demo_command():
    call_command("seed_demo", buyers=2, sellers=2, verbosity=0)
    assert Product.objects.count() == 10
    assert all(p.tags.count() == 2 for p in Product.objects.all())
    call_command("seed_demo", buyers=2, sellers=2, verbosity=0)
    assert Product.objects.count() == 10


@pytest.mark.django_db
def test_admin_pages_render(admin_client, product):
    for url in ("/admin/", "/admin/accounts/user/", "/admin/catalog/product/", "/admin/commerce/order/",
                "/admin/activity/useraction/", "/admin/catalog/product/%s/change/" % product.pk):
        assert admin_client.get(url).status_code == 200, url


@pytest.mark.django_db
def test_api_docs_render(api_client):
    assert api_client.get("/api/schema/").status_code == 200
    assert api_client.get("/api/docs/").status_code == 200
    assert api_client.get("/api/redoc/").status_code == 200


class ProductQuerySetTests(TestCase):
    """Kept as a unittest-style TestCase on purpose (mirrors the legacy suite)."""

    def setUp(self):
        self.store = StoreFactory()
        self.active = ProductFactory(store=self.store, title="Active")
        self.draft = ProductFactory(store=self.store, title="Draft", status=Product.Status.DRAFT)
        self.deleted = ProductFactory(store=self.store, title="Deleted")
        self.deleted.soft_delete()

    def test_published(self):
        self.assertQuerysetEqual(Product.objects.published(), [self.active], transform=lambda p: p)

    def test_visible_to_owner(self):
        self.assertQuerysetEqual(
            Product.objects.visible_to(self.store.owner).order_by("title"),
            ["Active", "Draft"],
            transform=lambda p: p.title,
        )

    def test_soft_deleted_hidden_from_default_manager(self):
        self.assertFalse(Product.objects.filter(pk=self.deleted.pk).exists())
        self.assertTrue(Product.all_objects.filter(pk=self.deleted.pk).exists())

    def test_status_change_sets_published_at(self):
        self.draft.status = Product.Status.ACTIVE
        self.draft.save()
        self.assertIsNotNone(self.draft.published_at)

    def test_discount(self):
        self.active.compare_at_price = Decimal("25.00")
        self.assertTrue(self.active.is_on_sale)
        self.assertEqual(self.active.discount_percent, Decimal("20.0"))
