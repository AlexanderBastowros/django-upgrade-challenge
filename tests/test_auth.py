import pytest

from apps.accounts.models import Profile, User

pytestmark = pytest.mark.django_db

REGISTER = "/api/v1/auth/register/"


def test_register_creates_user_and_profile(api_client):
    resp = api_client.post(
        REGISTER,
        {
            "username": "newbie",
            "email": "Newbie@Example.com",
            "password": "correct-horse-9",
            "password_confirm": "correct-horse-9",
            "accept_marketing": True,
        },
    )
    assert resp.status_code == 201, resp.data
    user = User.objects.get(username="newbie")
    assert user.email == "newbie@example.com"
    assert user.check_password("correct-horse-9")
    assert Profile.objects.get(user=user).marketing_opt_in is True


def test_register_marketing_unanswered_stays_null(api_client):
    resp = api_client.post(
        REGISTER,
        {"username": "quiet", "email": "q@example.com", "password": "correct-horse-9", "password_confirm": "correct-horse-9"},
    )
    assert resp.status_code == 201
    assert Profile.objects.get(user__username="quiet").marketing_opt_in is None


def test_register_rejects_mismatched_and_weak_passwords(api_client):
    resp = api_client.post(
        REGISTER, {"username": "x", "email": "x@example.com", "password": "abc", "password_confirm": "abd"}
    )
    assert resp.status_code == 400
    assert "password_confirm" in resp.data

    resp = api_client.post(
        REGISTER, {"username": "x", "email": "x@example.com", "password": "12345678", "password_confirm": "12345678"}
    )
    assert resp.status_code == 400


def test_register_rejects_duplicate_email(api_client, user):
    resp = api_client.post(
        REGISTER,
        {"username": "dupe", "email": user.email.upper(), "password": "correct-horse-9", "password_confirm": "correct-horse-9"},
    )
    assert resp.status_code == 400
    assert "email" in resp.data


def test_jwt_obtain_refresh_verify_and_use(api_client, user):
    resp = api_client.post("/api/v1/auth/token/", {"username": "alice", "password": "s3cret-pass!"})
    assert resp.status_code == 200, resp.data
    access, refresh = resp.data["access"], resp.data["refresh"]

    assert api_client.post("/api/v1/auth/token/verify/", {"token": access}).status_code == 200
    refreshed = api_client.post("/api/v1/auth/token/refresh/", {"refresh": refresh})
    assert refreshed.status_code == 200 and "access" in refreshed.data

    api_client.credentials(HTTP_AUTHORIZATION="Bearer " + access)
    me = api_client.get("/api/v1/auth/me/")
    assert me.status_code == 200
    assert me.data["username"] == "alice"


def test_bad_credentials_rejected(api_client, user):
    resp = api_client.post("/api/v1/auth/token/", {"username": "alice", "password": "nope"})
    assert resp.status_code == 401


def test_anonymous_cannot_access_me(api_client):
    assert api_client.get("/api/v1/auth/me/").status_code == 401


def test_update_me(client_user):
    resp = client_user.patch("/api/v1/auth/me/", {"display_name": "Alice L.", "username": "hacker"})
    assert resp.status_code == 200
    assert resp.data["display_name"] == "Alice L."
    assert resp.data["username"] == "alice"  # read-only


def test_change_password(client_user, user):
    resp = client_user.post(
        "/api/v1/auth/password/change/", {"old_password": "wrong", "new_password": "brand-new-pass-1"}
    )
    assert resp.status_code == 400
    resp = client_user.post(
        "/api/v1/auth/password/change/", {"old_password": "s3cret-pass!", "new_password": "brand-new-pass-1"}
    )
    assert resp.status_code == 200
    user.refresh_from_db()
    assert user.check_password("brand-new-pass-1")


def test_email_verification_roundtrip(client_user, api_client, user):
    token = client_user.post("/api/v1/auth/email/verify/request/").data["token"]
    assert api_client.post("/api/v1/auth/email/verify/confirm/", {"token": token + "x"}).status_code == 400
    resp = api_client.post("/api/v1/auth/email/verify/confirm/", {"token": token})
    assert resp.status_code == 200
    user.refresh_from_db()
    assert user.email_verified is True


def test_logout_blacklists_refresh_token(api_client, client_user, user):
    tokens = api_client.post("/api/v1/auth/token/", {"username": "alice", "password": "s3cret-pass!"}).data
    assert client_user.post("/api/v1/auth/logout/", {"refresh": tokens["refresh"]}).status_code == 205
    resp = api_client.post("/api/v1/auth/token/refresh/", {"refresh": tokens["refresh"]})
    assert resp.status_code == 401


def test_cannot_logout_someone_elses_token(api_client, client_other, user):
    tokens = api_client.post("/api/v1/auth/token/", {"username": "alice", "password": "s3cret-pass!"}).data
    assert client_other.post("/api/v1/auth/logout/", {"refresh": tokens["refresh"]}).status_code == 400
