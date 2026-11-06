import random
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import Address, Follow, User
from apps.catalog.models import Category, Product, Review, Store, Tag
from apps.commerce import services
from apps.commerce.models import Coupon

DEMO_PASSWORD = "demo-pass-123"

PRODUCT_NAMES = [
    "Ceramic Mug", "Walnut Cutting Board", "Linen Apron", "Beeswax Candle", "Leather Wallet",
    "Wool Beanie", "Bamboo Speaker", "Desk Lamp", "Cotton Tote", "Glass Teapot",
    "Copper Bottle", "Notebook Set", "Silver Ring", "Plant Pot", "Throw Blanket",
]


class Command(BaseCommand):
    help = "Populate the database with demo users, stores, products and orders."

    def add_arguments(self, parser):
        parser.add_argument("--buyers", type=int, default=5)
        parser.add_argument("--sellers", type=int, default=3)
        parser.add_argument("--seed", type=int, default=42)

    @transaction.atomic
    def handle(self, *args, **options):
        rng = random.Random(options["seed"])
        admin, created = User.objects.get_or_create(
            username="admin", defaults={"email": "admin@example.com", "is_staff": True, "is_superuser": True}
        )
        if created:
            admin.set_password(DEMO_PASSWORD)
            admin.save()

        tags = [Tag.objects.get_or_create(name=name)[0] for name in ("handmade", "eco", "gift", "sale", "new")]
        categories = list(Category.objects.filter(parent__isnull=False)) or list(Category.objects.all())

        sellers = []
        for i in range(options["sellers"]):
            seller, created = User.objects.get_or_create(
                username="seller%d" % i,
                defaults={"email": "seller%d@example.com" % i, "is_seller": True, "display_name": "Seller %d" % i},
            )
            if created:
                seller.set_password(DEMO_PASSWORD)
                seller.save()
            store, _ = Store.objects.get_or_create(
                owner=seller, name="Demo Store %d" % i, defaults={"status": Store.Status.ACTIVE}
            )
            for name in rng.sample(PRODUCT_NAMES, 5):
                Product.objects.get_or_create(
                    store=store,
                    title=name,
                    defaults={
                        "price": Decimal(rng.randint(500, 9000)) / 100,
                        "stock": rng.randint(5, 50),
                        "status": Product.Status.ACTIVE,
                        "category": rng.choice(categories) if categories else None,
                    },
                )
            Coupon.objects.get_or_create(
                code="DEMO%d" % i, defaults={"store": store, "created_by": seller, "value": Decimal("10")}
            )
            sellers.append(seller)

        for product in Product.objects.prefetch_related("tags").iterator():
            if not product.tags.exists():
                product.tags.add(*rng.sample(tags, 2))

        products = list(Product.objects.published().select_related("store"))
        for i in range(options["buyers"]):
            buyer, created = User.objects.get_or_create(
                username="buyer%d" % i, defaults={"email": "buyer%d@example.com" % i, "display_name": "Buyer %d" % i}
            )
            if not created:
                continue
            buyer.set_password(DEMO_PASSWORD)
            buyer.save()
            address = Address.objects.create(
                user=buyer, full_name=buyer.display_name, line1="%d Demo Street" % (i + 1),
                city="Springfield", postal_code="12345", country="US", is_default=True,
            )
            for seller in rng.sample(sellers, min(2, len(sellers))):
                Follow.objects.get_or_create(follower=buyer, followee=seller)
            picks = rng.sample(products, min(3, len(products)))
            order = services.create_order(buyer, [(p, None, 1) for p in picks], shipping_address=address)
            services.pay_order(order, buyer)
            for p in picks[:2]:
                Review.objects.get_or_create(product=p, author=buyer, defaults={"rating": rng.randint(3, 5), "is_verified_purchase": True})

        self.stdout.write(self.style.SUCCESS(
            "Seeded %d users, %d stores, %d products. Password for all demo users: %s"
            % (User.objects.count(), Store.objects.count(), Product.objects.count(), DEMO_PASSWORD)
        ))
