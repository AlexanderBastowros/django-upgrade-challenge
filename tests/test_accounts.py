import pytest

from apps.accounts.models import Address, Follow, User
from apps.activity.models import Notification

from .factories import AddressFactory, UserFactory

pytestmark = pytest.mark.django_db


class TestUsers:
    def test_list_and_retrieve(self, client_user, other_user):
        resp = client_user.get("/api/v1/users/")
        assert resp.status_code == 200
        assert resp.data["count"] == 2
        assert "email" not in resp.data["results"][0]  # public serializer

        resp = client_user.get("/api/v1/users/%s/" % other_user.pk)
        assert resp.data["username"] == "bob"
        assert resp.data["followers_count"] == 0

    def test_search_and_filter(self, client_user, seller):
        resp = client_user.get("/api/v1/users/", {"is_seller": "true"})
        assert [u["username"] for u in resp.data["results"]] == ["sam_seller"]
        resp = client_user.get("/api/v1/users/", {"search": "ali"})
        assert [u["username"] for u in resp.data["results"]] == ["alice"]

    def test_update_self_but_not_others(self, client_user, user, other_user):
        assert client_user.patch("/api/v1/users/%s/" % user.pk, {"display_name": "A"}).status_code == 200
        assert client_user.patch("/api/v1/users/%s/" % other_user.pk, {"display_name": "B"}).status_code == 403

    def test_only_staff_can_create_and_delete(self, client_user, client_staff, other_user):
        payload = {"username": "made", "email": "made@example.com", "password": "pw-123456789"}
        assert client_user.post("/api/v1/users/", payload).status_code == 403
        resp = client_staff.post("/api/v1/users/", payload)
        assert resp.status_code == 201, resp.data
        assert User.objects.get(username="made").check_password("pw-123456789")

        assert client_user.delete("/api/v1/users/%s/" % other_user.pk).status_code == 403
        assert client_staff.delete("/api/v1/users/%s/" % other_user.pk).status_code == 204
        other_user.refresh_from_db()
        assert other_user.is_active is False

    def test_staff_reset_password(self, client_staff, other_user):
        resp = client_staff.post("/api/v1/users/%s/reset-password/" % other_user.pk)
        assert resp.status_code == 200
        other_user.refresh_from_db()
        assert other_user.check_password(resp.data["temporary_password"])

    def test_follow_unfollow_flow(self, client_user, user, other_user):
        resp = client_user.post("/api/v1/users/%s/follow/" % other_user.pk)
        assert resp.status_code == 201
        assert client_user.post("/api/v1/users/%s/follow/" % other_user.pk).status_code == 200  # idempotent
        assert Notification.objects.filter(recipient=other_user).count() == 1

        followers = client_user.get("/api/v1/users/%s/followers/" % other_user.pk)
        assert [u["username"] for u in followers.data["results"]] == ["alice"]
        following = client_user.get("/api/v1/users/%s/following/" % user.pk)
        assert [u["username"] for u in following.data["results"]] == ["bob"]
        assert client_user.get("/api/v1/users/%s/" % other_user.pk).data["is_followed"] is True

        assert client_user.post("/api/v1/users/%s/unfollow/" % other_user.pk).status_code == 204
        assert not Follow.objects.exists()

    def test_cannot_follow_self(self, client_user, user):
        assert client_user.post("/api/v1/users/%s/follow/" % user.pk).status_code == 409


class TestProfiles:
    def test_profile_created_automatically(self, client_user, user):
        resp = client_user.get("/api/v1/profiles/mine/")
        assert resp.status_code == 200
        assert resp.data["user"]["id"] == user.pk

    def test_owner_can_edit_and_others_cannot(self, client_user, client_other, user):
        pk = user.profile.pk
        resp = client_user.patch(
            "/api/v1/profiles/%s/" % pk,
            {"bio": "hi", "timezone": "Europe/London", "marketing_opt_in": False, "social_links": {"twitter": "x"}},
        )
        assert resp.status_code == 200, resp.data
        assert resp.data["marketing_opt_in"] is False
        assert client_other.patch("/api/v1/profiles/%s/" % pk, {"bio": "pwned"}).status_code == 403
        assert client_other.get("/api/v1/profiles/%s/" % pk).status_code == 200

    def test_validation(self, client_user, user):
        pk = user.profile.pk
        assert client_user.patch("/api/v1/profiles/%s/" % pk, {"timezone": "Mars/Base"}).status_code == 400
        assert client_user.patch("/api/v1/profiles/%s/" % pk, {"social_links": {"myspace": "x"}}).status_code == 400

    def test_cannot_create_second_profile(self, client_user):
        assert client_user.post("/api/v1/profiles/", {"bio": "dupe"}).status_code == 400

    def test_delete_and_recreate(self, client_user, user):
        assert client_user.delete("/api/v1/profiles/%s/" % user.profile.pk).status_code == 204
        assert client_user.post("/api/v1/profiles/", {"bio": "again"}).status_code == 201


class TestAddresses:
    payload = {"full_name": "Alice", "line1": "1 Main St", "city": "Boston", "postal_code": "02101", "country": "us"}

    def test_crud(self, client_user):
        resp = client_user.post("/api/v1/addresses/", self.payload)
        assert resp.status_code == 201, resp.data
        assert resp.data["country"] == "US"
        pk = resp.data["id"]
        assert client_user.get("/api/v1/addresses/").data["count"] == 1
        assert client_user.patch("/api/v1/addresses/%s/" % pk, {"label": "Home"}).data["label"] == "Home"
        assert client_user.delete("/api/v1/addresses/%s/" % pk).status_code == 204

    def test_private_to_owner(self, client_other, address):
        assert client_other.get("/api/v1/addresses/").data["count"] == 0
        assert client_other.get("/api/v1/addresses/%s/" % address.pk).status_code == 404

    def test_single_default_per_kind(self, client_user, user):
        first = client_user.post("/api/v1/addresses/", dict(self.payload, is_default=True)).data
        second = client_user.post("/api/v1/addresses/", dict(self.payload, line1="2 Main St", is_default=True)).data
        assert Address.objects.get(pk=first["id"]).is_default is False
        assert Address.objects.get(pk=second["id"]).is_default is True

        client_user.post("/api/v1/addresses/%s/set-default/" % first["id"])
        assert Address.objects.get(pk=first["id"]).is_default is True
        assert Address.objects.get(pk=second["id"]).is_default is False

    def test_invalid_country(self, client_user):
        assert client_user.post("/api/v1/addresses/", dict(self.payload, country="USA")).status_code == 400


class TestFollows:
    def test_crud(self, client_user, other_user):
        resp = client_user.post("/api/v1/follows/", {"followee_id": other_user.pk})
        assert resp.status_code == 201, resp.data
        pk = resp.data["id"]
        assert client_user.post("/api/v1/follows/", {"followee_id": other_user.pk}).status_code == 400
        assert client_user.patch("/api/v1/follows/%s/" % pk, {"notify": False}).data["notify"] is False
        assert client_user.get("/api/v1/follows/", {"followee": other_user.pk}).data["count"] == 1
        assert client_user.delete("/api/v1/follows/%s/" % pk).status_code == 204

    def test_cannot_follow_self(self, client_user, user):
        assert client_user.post("/api/v1/follows/", {"followee_id": user.pk}).status_code == 400

    def test_cannot_see_others_follows(self, client_other, user):
        target = UserFactory(username="carol")
        Follow.objects.create(follower=user, followee=target)
        assert client_other.get("/api/v1/follows/").data["count"] == 0
