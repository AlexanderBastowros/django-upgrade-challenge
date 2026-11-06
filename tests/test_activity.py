import csv
import io

import pytest

from apps.activity.models import Notification, SavedSearch, UserAction

from .factories import ProductFactory

pytestmark = pytest.mark.django_db


class TestUserActions:
    def test_writes_are_logged_automatically(self, client_user, user):
        client_user.post(
            "/api/v1/addresses/",
            {"full_name": "A", "line1": "1 St", "city": "X", "postal_code": "1", "country": "US"},
            HTTP_USER_AGENT="pytest-agent",
            HTTP_X_FORWARDED_FOR="203.0.113.9, 10.0.0.1",
        )
        action = UserAction.objects.get(user=user)
        assert action.verb == "created"
        assert action.content_type.model == "address"
        assert action.ip_address == "203.0.113.9"
        assert action.user_agent == "pytest-agent"

    def test_client_can_record_allowed_verbs(self, client_user, product):
        resp = client_user.post(
            "/api/v1/actions/",
            {"verb": "viewed", "target_type_input": "product", "object_id": str(product.pk), "metadata": {"ref": "home"}},
        )
        assert resp.status_code == 201, resp.data
        assert resp.data["target_type"] == "product"
        assert resp.data["target_repr"] == product.title
        assert client_user.post("/api/v1/actions/", {"verb": "paid"}).status_code == 400
        assert client_user.post(
            "/api/v1/actions/", {"verb": "viewed", "target_type_input": "product", "object_id": "999999"}
        ).status_code == 400

    def test_update_delete_and_privacy(self, client_user, client_other):
        pk = client_user.post("/api/v1/actions/", {"verb": "searched", "metadata": {"q": "mug"}}).data["id"]
        assert client_user.patch("/api/v1/actions/%s/" % pk, {"metadata": {"q": "mugs"}}).data["metadata"] == {"q": "mugs"}
        assert client_user.patch("/api/v1/actions/%s/" % pk, {"verb": "viewed"}).status_code == 400
        assert client_other.get("/api/v1/actions/%s/" % pk).status_code == 404
        assert client_user.delete("/api/v1/actions/%s/" % pk).status_code == 204

    def test_summary(self, client_user):
        for verb in ("viewed", "viewed", "searched"):
            client_user.post("/api/v1/actions/", {"verb": verb})
        resp = client_user.get("/api/v1/actions/summary/")
        assert resp.data == [{"verb": "viewed", "count": 2}, {"verb": "searched", "count": 1}]

    def test_csv_export(self, client_user, product):
        client_user.post("/api/v1/actions/", {"verb": "viewed", "target_type_input": "product", "object_id": str(product.pk)})
        resp = client_user.get("/api/v1/actions/export/")
        assert resp.status_code == 200
        assert resp["Content-Type"] == "text/csv"
        rows = list(csv.reader(io.StringIO(resp.content.decode())))
        assert rows[0] == ["date", "verb", "target_type", "object_id", "target", "ip"]
        assert rows[1][1:5] == ["viewed", "product", str(product.pk), product.title]

    def test_staff_all_flag(self, client_staff, client_user):
        client_user.post("/api/v1/actions/", {"verb": "viewed"})
        assert client_staff.get("/api/v1/actions/").data["count"] == 0
        assert client_staff.get("/api/v1/actions/", {"all": "1"}).data["count"] == 1


class TestNotifications:
    def test_lifecycle(self, client_user, client_staff, user):
        resp = client_staff.post("/api/v1/notifications/", {"recipient": user.pk, "title": "Welcome", "level": "info"})
        assert resp.status_code == 201, resp.data
        assert client_user.post("/api/v1/notifications/", {"recipient": user.pk, "title": "x"}).status_code == 403

        pk = resp.data["id"]
        assert client_user.get("/api/v1/notifications/unread-count/").data == {"unread": 1}
        updated = client_user.patch("/api/v1/notifications/%s/" % pk, {"is_read": True, "title": "hacked"})
        assert updated.data["is_read"] is True and updated.data["read_at"] is not None
        assert updated.data["title"] == "Welcome"
        assert client_user.patch("/api/v1/notifications/%s/" % pk, {"is_read": False}).data["read_at"] is None
        assert client_user.post("/api/v1/notifications/%s/mark-read/" % pk).data["is_read"] is True
        assert client_user.delete("/api/v1/notifications/%s/" % pk).status_code == 204

    def test_mark_all_read(self, client_user, user):
        Notification.objects.bulk_create([Notification(recipient=user, title="n%d" % i) for i in range(3)])
        assert client_user.post("/api/v1/notifications/mark-all-read/").data["count"] == 3
        assert client_user.get("/api/v1/notifications/", {"is_read": "false"}).data["count"] == 0

    def test_private(self, client_other, user):
        n = Notification.objects.create(recipient=user, title="secret")
        assert client_other.get("/api/v1/notifications/%s/" % n.pk).status_code == 404


class TestSavedSearches:
    def test_crud_and_run(self, client_user, store):
        ProductFactory(store=store, title="Green Mug", price="8.00")
        ProductFactory(store=store, title="Green Vase", price="80.00")
        resp = client_user.post(
            "/api/v1/saved-searches/",
            {"name": "Cheap green", "query": "green", "filters": {"max_price": "10"}, "notify_frequency": "weekly"},
        )
        assert resp.status_code == 201, resp.data
        pk = resp.data["id"]
        assert client_user.post("/api/v1/saved-searches/", {"name": "Cheap green"}).status_code == 400
        assert client_user.post("/api/v1/saved-searches/", {"name": "Bad", "filters": {"evil": 1}}).status_code == 400

        run = client_user.post("/api/v1/saved-searches/%s/run/" % pk)
        assert [p["title"] for p in run.data["results"]] == ["Green Mug"]
        assert SavedSearch.objects.get(pk=pk).last_run_at is not None

        assert client_user.put("/api/v1/saved-searches/%s/" % pk, {"name": "Green", "query": "green"}).status_code == 200
        assert client_user.delete("/api/v1/saved-searches/%s/" % pk).status_code == 204
