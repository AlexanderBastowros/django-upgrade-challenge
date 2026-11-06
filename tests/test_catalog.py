import io
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from apps.activity.models import Notification
from apps.catalog.models import Product, ProductImage, Review, Store
from apps.commerce import services

from .factories import CategoryFactory, ProductFactory, StoreFactory, TagFactory, VariantFactory

pytestmark = pytest.mark.django_db


def make_png(name="pic.png", size=(800, 600)):
    buf = io.BytesIO()
    Image.new("RGB", size, (200, 30, 30)).save(buf, format="PNG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


class TestCategoriesAndTags:
    def test_seeded_categories_are_public(self, api_client):
        resp = api_client.get("/api/v1/categories/", {"root": "true"})
        assert resp.status_code == 200
        assert {"electronics", "books"} <= {c["slug"] for c in resp.data["results"]}

    def test_only_staff_can_write(self, client_user, client_staff):
        assert client_user.post("/api/v1/categories/", {"name": "Toys"}).status_code == 403
        resp = client_staff.post("/api/v1/categories/", {"name": "Toys"})
        assert resp.status_code == 201
        assert resp.data["slug"] == "toys"
        child = client_staff.post("/api/v1/categories/", {"name": "Lego", "parent_id": resp.data["id"]}).data
        assert child["path"] == "Toys / Lego"
        children = client_staff.get("/api/v1/categories/%s/children/" % resp.data["id"])
        assert [c["name"] for c in children.data] == ["Lego"]
        assert client_staff.patch("/api/v1/categories/%s/" % resp.data["id"], {"parent_id": child["id"]}).status_code == 400
        assert client_staff.delete("/api/v1/categories/%s/" % child["id"]).status_code == 204

    def test_tags_crud(self, client_staff, api_client):
        resp = client_staff.post("/api/v1/tags/", {"name": "Eco Friendly"})
        assert resp.status_code == 201 and resp.data["slug"] == "eco-friendly"
        assert client_staff.put("/api/v1/tags/%s/" % resp.data["id"], {"name": "Green"}).data["name"] == "Green"
        assert api_client.get("/api/v1/tags/").data["count"] == 1
        assert client_staff.delete("/api/v1/tags/%s/" % resp.data["id"]).status_code == 204


class TestStores:
    def test_only_sellers_can_open_stores(self, client_user, client_seller, seller):
        assert client_user.post("/api/v1/stores/", {"name": "Nope"}).status_code == 400
        resp = client_seller.post("/api/v1/stores/", {"name": "Sam's Second Shop", "status": "active"})
        assert resp.status_code == 201
        assert resp.data["status"] == "pending"  # read-only, needs staff approval
        assert resp.data["owner"]["id"] == seller.pk

    def test_pending_store_hidden_from_public(self, api_client, client_seller, seller):
        pending = StoreFactory(owner=seller, status=Store.Status.PENDING)
        assert api_client.get("/api/v1/stores/%s/" % pending.pk).status_code == 404
        assert client_seller.get("/api/v1/stores/%s/" % pending.pk).status_code == 200

    def test_staff_sets_status(self, client_staff, client_seller, seller):
        store = StoreFactory(owner=seller, status=Store.Status.PENDING)
        assert client_seller.post("/api/v1/stores/%s/set-status/" % store.pk, {"status": "active"}).status_code == 403
        resp = client_staff.post("/api/v1/stores/%s/set-status/" % store.pk, {"status": "active"})
        assert resp.data["status"] == "active"

    def test_owner_updates_others_cannot(self, client_seller, client_user, store):
        assert client_seller.patch("/api/v1/stores/%s/" % store.pk, {"description": "Mugs"}).status_code == 200
        assert client_user.patch("/api/v1/stores/%s/" % store.pk, {"description": "x"}).status_code == 403

    def test_close_archives_products(self, client_seller, store, product):
        resp = client_seller.post("/api/v1/stores/%s/close/" % store.pk)
        assert resp.data["status"] == "closed"
        product.refresh_from_db()
        assert product.status == Product.Status.ARCHIVED

    def test_stats(self, client_seller, client_user, store, product, user):
        services.pay_order(services.create_order(user, [(product, None, 2)]), user)
        resp = client_seller.get("/api/v1/stores/%s/stats/" % store.pk)
        assert resp.status_code == 200
        assert resp.data["order_count"] == 1
        assert Decimal(resp.data["gross_revenue"]) == Decimal("25.00")
        assert client_user.get("/api/v1/stores/%s/stats/" % store.pk).status_code == 403

    def test_delete_store_with_orders_conflicts(self, client_seller, store, product, user):
        services.create_order(user, [(product, None, 1)])
        assert client_seller.delete("/api/v1/stores/%s/" % store.pk).status_code == 409

    def test_delete_empty_store(self, client_seller, store):
        assert client_seller.delete("/api/v1/stores/%s/" % store.pk).status_code == 204


class TestProducts:
    def payload(self, store, **extra):
        data = {"store_id": store.pk, "title": "Red Mug", "price": "9.99", "stock": 3, "tags": []}
        data.update(extra)
        return data

    def test_create_as_owner(self, client_seller, store):
        tag = TagFactory(name="ceramic")
        resp = client_seller.post("/api/v1/products/", self.payload(store, tags=["ceramic"]))
        assert resp.status_code == 201, resp.data
        assert resp.data["status"] == "draft"
        assert resp.data["tags"] == [tag.name]
        assert resp.data["slug"] == "red-mug"
        assert "title=Red%20Mug" in resp.data["share_url"]

    def test_cannot_create_in_others_store(self, client_user, store):
        assert client_user.post("/api/v1/products/", self.payload(store)).status_code == 400

    def test_price_validation(self, client_seller, store):
        assert client_seller.post("/api/v1/products/", self.payload(store, price="-1")).status_code == 400
        resp = client_seller.post("/api/v1/products/", self.payload(store, compare_at_price="5.00"))
        assert resp.status_code == 400 and "compare_at_price" in resp.data

    def test_only_staff_can_feature(self, client_seller, client_staff, store, product):
        assert client_seller.patch("/api/v1/products/%s/" % product.pk, {"is_featured": True}).status_code == 400
        assert client_staff.patch("/api/v1/products/%s/" % product.pk, {"is_featured": True}).status_code == 200
        assert client_seller.get("/api/v1/products/featured/").data["count"] == 1

    def test_visibility(self, api_client, client_seller, client_user, store, product):
        draft = ProductFactory(store=store, status=Product.Status.DRAFT)
        public_ids = {p["id"] for p in api_client.get("/api/v1/products/").data["results"]}
        assert product.pk in public_ids and draft.pk not in public_ids
        assert client_user.get("/api/v1/products/%s/" % draft.pk).status_code == 404
        assert client_seller.get("/api/v1/products/%s/" % draft.pk).status_code == 200

    def test_filters_and_ordering(self, api_client, store):
        cat = CategoryFactory(name="Kitchenware")
        ProductFactory(store=store, title="Cheap", price="5.00", category=cat)
        ProductFactory(store=store, title="Pricey", price="50.00", compare_at_price="80.00", stock=0)
        resp = api_client.get("/api/v1/products/", {"max_price": "10", "category": cat.slug})
        assert [p["title"] for p in resp.data["results"]] == ["Cheap"]
        resp = api_client.get("/api/v1/products/", {"on_sale": "true"})
        assert [p["title"] for p in resp.data["results"]] == ["Pricey"]
        resp = api_client.get("/api/v1/products/", {"in_stock": "false"})
        assert [p["title"] for p in resp.data["results"]] == ["Pricey"]
        resp = api_client.get("/api/v1/products/", {"ordering": "-price"})
        assert resp.data["results"][0]["title"] == "Pricey"

    def test_publish_archive_transitions(self, client_seller, store):
        product = ProductFactory(store=store, status=Product.Status.DRAFT)
        resp = client_seller.post("/api/v1/products/%s/publish/" % product.pk)
        assert resp.status_code == 200 and resp.data["status"] == "active"
        assert client_seller.post("/api/v1/products/%s/publish/" % product.pk).status_code == 409
        assert client_seller.post("/api/v1/products/%s/archive/" % product.pk).data["status"] == "archived"

    def test_publish_notifies_followers(self, client_seller, client_user, store, seller, user):
        client_user.post("/api/v1/users/%s/follow/" % seller.pk)
        product = ProductFactory(store=store, status=Product.Status.DRAFT)
        client_seller.post("/api/v1/products/%s/publish/" % product.pk)
        assert Notification.objects.filter(recipient=user, title__contains=product.title).exists()

    def test_cannot_publish_when_store_pending(self, client_seller, seller):
        store = StoreFactory(owner=seller, status=Store.Status.PENDING)
        product = ProductFactory(store=store, status=Product.Status.DRAFT)
        assert client_seller.post("/api/v1/products/%s/publish/" % product.pk).status_code == 409

    def test_adjust_stock(self, client_seller, client_user, product):
        resp = client_seller.post("/api/v1/products/%s/adjust-stock/" % product.pk, {"delta": 5})
        assert resp.status_code == 200 and resp.data["stock"] == 15
        assert client_seller.post("/api/v1/products/%s/adjust-stock/" % product.pk, {"delta": -100}).status_code == 409
        assert client_user.post("/api/v1/products/%s/adjust-stock/" % product.pk, {"delta": 1}).status_code == 403

    def test_related(self, api_client, store, product):
        sibling = ProductFactory(store=store, category=product.category)
        ProductFactory(store=store)
        resp = api_client.get("/api/v1/products/%s/related/" % product.pk)
        assert [p["id"] for p in resp.data] == [sibling.pk]

    def test_soft_delete(self, client_seller, api_client, product):
        assert client_seller.delete("/api/v1/products/%s/" % product.pk).status_code == 204
        assert Product.all_objects.get(pk=product.pk).is_deleted is True
        assert api_client.get("/api/v1/products/%s/" % product.pk).status_code == 404

    def test_put_update(self, client_seller, store, product):
        resp = client_seller.put("/api/v1/products/%s/" % product.pk, self.payload(store, title="Blue Mug XL", price="15.00"))
        assert resp.status_code == 200, resp.data
        assert resp.data["title"] == "Blue Mug XL"
        assert resp.data["slug"] == product.slug  # slug is stable


class TestProductImages:
    def test_upload_creates_thumbnail_and_primary(self, client_seller, product):
        resp = client_seller.post(
            "/api/v1/product-images/", {"product": product.pk, "image": make_png(), "is_primary": True}, format="multipart"
        )
        assert resp.status_code == 201, resp.data
        image = ProductImage.objects.get(pk=resp.data["id"])
        assert image.thumbnail
        with Image.open(image.thumbnail.path) as thumb:
            assert max(thumb.size) <= 320

        second = client_seller.post(
            "/api/v1/product-images/", {"product": product.pk, "image": make_png("b.png"), "is_primary": True}, format="multipart"
        ).data
        image.refresh_from_db()
        assert image.is_primary is False
        assert client_seller.patch("/api/v1/product-images/%s/" % second["id"], {"alt_text": "Side view"}).data["alt_text"] == "Side view"
        assert client_seller.delete("/api/v1/product-images/%s/" % second["id"]).status_code == 204

    def test_others_cannot_upload(self, client_user, product):
        resp = client_user.post("/api/v1/product-images/", {"product": product.pk, "image": make_png()}, format="multipart")
        assert resp.status_code == 400

    def test_primary_image_in_listing(self, client_seller, api_client, product):
        client_seller.post("/api/v1/product-images/", {"product": product.pk, "image": make_png()}, format="multipart")
        listed = api_client.get("/api/v1/products/").data["results"][0]
        assert listed["primary_image"].startswith("http://testserver/media/products/")


class TestVariants:
    def test_crud(self, client_seller, product, api_client):
        resp = client_seller.post(
            "/api/v1/product-variants/",
            {"product": product.pk, "name": "Large", "sku": "MUG-L", "price_delta": "2.50", "attributes": {"size": "L"}},
        )
        assert resp.status_code == 201, resp.data
        assert Decimal(resp.data["price"]) == Decimal("15.00")
        pk = resp.data["id"]
        assert api_client.get("/api/v1/product-variants/", {"product": product.pk}).data["count"] == 1
        assert client_seller.patch("/api/v1/product-variants/%s/" % pk, {"stock": 7}).data["stock"] == 7
        assert client_seller.patch("/api/v1/product-variants/%s/" % pk, {"price_delta": "-50"}).status_code == 400
        assert client_seller.delete("/api/v1/product-variants/%s/" % pk).status_code == 204

    def test_non_owner_forbidden(self, client_user, product):
        variant = VariantFactory(product=product)
        assert client_user.patch("/api/v1/product-variants/%s/" % variant.pk, {"stock": 1}).status_code == 403
        resp = client_user.post("/api/v1/product-variants/", {"product": product.pk, "name": "X", "sku": "X1"})
        assert resp.status_code == 400


class TestReviews:
    def test_create_and_rating_aggregate(self, client_user, client_other, api_client, product):
        assert client_user.post("/api/v1/reviews/", {"product": product.pk, "rating": 5, "title": "Great"}).status_code == 201
        assert client_other.post("/api/v1/reviews/", {"product": product.pk, "rating": 2}).status_code == 201
        listed = api_client.get("/api/v1/products/").data["results"][0]
        assert listed["rating_avg"] == 3.5 and listed["rating_count"] == 2

    def test_one_review_per_user(self, client_user, product):
        client_user.post("/api/v1/reviews/", {"product": product.pk, "rating": 5})
        resp = client_user.post("/api/v1/reviews/", {"product": product.pk, "rating": 4})
        assert resp.status_code == 400

    def test_can_review_again_after_deleting(self, client_user, product):
        pk = client_user.post("/api/v1/reviews/", {"product": product.pk, "rating": 5}).data["id"]
        assert client_user.delete("/api/v1/reviews/%s/" % pk).status_code == 204
        assert Review.all_objects.get(pk=pk).is_deleted
        assert client_user.post("/api/v1/reviews/", {"product": product.pk, "rating": 3}).status_code == 201

    def test_rating_bounds_and_own_product(self, client_user, client_seller, product):
        assert client_user.post("/api/v1/reviews/", {"product": product.pk, "rating": 6}).status_code == 400
        assert client_seller.post("/api/v1/reviews/", {"product": product.pk, "rating": 5}).status_code == 400

    def test_verified_purchase(self, client_user, user, product):
        services.pay_order(services.create_order(user, [(product, None, 1)]), user)
        resp = client_user.post("/api/v1/reviews/", {"product": product.pk, "rating": 4})
        assert resp.data["is_verified_purchase"] is True

    def test_update_and_helpful(self, client_user, client_other, product):
        pk = client_user.post("/api/v1/reviews/", {"product": product.pk, "rating": 3}).data["id"]
        assert client_user.patch("/api/v1/reviews/%s/" % pk, {"rating": 4}).data["rating"] == 4
        assert client_other.patch("/api/v1/reviews/%s/" % pk, {"rating": 1}).status_code == 403
        assert client_other.post("/api/v1/reviews/%s/helpful/" % pk).data["helpful_count"] == 1
        assert client_user.post("/api/v1/reviews/%s/helpful/" % pk).status_code == 409


class TestQuestions:
    def test_ask_and_answer(self, client_user, client_seller, client_other, product):
        resp = client_user.post("/api/v1/questions/", {"product": product.pk, "question": "Dishwasher safe?"})
        assert resp.status_code == 201
        pk = resp.data["id"]
        assert client_other.post("/api/v1/questions/%s/answer/" % pk, {"answer": "No"}).status_code == 403
        answered = client_seller.post("/api/v1/questions/%s/answer/" % pk, {"answer": "Yes!"})
        assert answered.data["is_answered"] is True
        assert client_user.get("/api/v1/questions/", {"answered": "true"}).data["count"] == 1

    def test_private_questions(self, client_user, client_other, client_seller, product):
        pk = client_user.post("/api/v1/questions/", {"product": product.pk, "question": "Hi", "is_public": False}).data["id"]
        assert client_other.get("/api/v1/questions/%s/" % pk).status_code == 404
        assert client_seller.get("/api/v1/questions/%s/" % pk).status_code == 200
        assert client_user.put("/api/v1/questions/%s/" % pk, {"product": product.pk, "question": "Hello"}).status_code == 200
        assert client_user.delete("/api/v1/questions/%s/" % pk).status_code == 204
