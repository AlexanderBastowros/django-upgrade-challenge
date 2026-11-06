import pytest
from rest_framework.test import APIClient

from . import factories


@pytest.fixture(autouse=True)
def _fast_and_isolated(settings, tmp_path):
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]
    settings.MEDIA_ROOT = str(tmp_path / "media")
    settings.REST_FRAMEWORK = {
        **settings.REST_FRAMEWORK,
        "DEFAULT_THROTTLE_CLASSES": (),
    }


@pytest.fixture
def api_client():
    return APIClient()


def _client_for(user):
    client = APIClient()
    client.force_authenticate(user=user)
    client.user = user
    return client


@pytest.fixture
def user(db):
    return factories.UserFactory(username="alice")


@pytest.fixture
def other_user(db):
    return factories.UserFactory(username="bob")


@pytest.fixture
def seller(db):
    return factories.SellerFactory(username="sam_seller")


@pytest.fixture
def staff(db):
    return factories.StaffFactory(username="sid_staff")


@pytest.fixture
def client_user(user):
    return _client_for(user)


@pytest.fixture
def client_other(other_user):
    return _client_for(other_user)


@pytest.fixture
def client_seller(seller):
    return _client_for(seller)


@pytest.fixture
def client_staff(staff):
    return _client_for(staff)


@pytest.fixture
def store(seller):
    return factories.StoreFactory(owner=seller, name="Sam's Shop")


@pytest.fixture
def product(store):
    return factories.ProductFactory(store=store, title="Blue Mug", price="12.50", stock=10)


@pytest.fixture
def address(user):
    return factories.AddressFactory(user=user)
