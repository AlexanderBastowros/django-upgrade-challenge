from django.db import migrations
from django.utils.text import slugify

DEFAULT_CATEGORIES = {
    "Electronics": ["Phones", "Laptops", "Audio"],
    "Home & Garden": ["Kitchen", "Furniture", "Outdoor"],
    "Fashion": ["Women", "Men", "Accessories"],
    "Books": [],
    "Handmade": ["Jewelry", "Ceramics"],
}


def seed(apps, schema_editor):
    Category = apps.get_model("catalog", "Category")
    for position, (root_name, children) in enumerate(DEFAULT_CATEGORIES.items()):
        root, _ = Category.objects.get_or_create(
            slug=slugify(root_name), defaults={"name": root_name, "position": position}
        )
        for child_position, child_name in enumerate(children):
            Category.objects.get_or_create(
                slug="%s-%s" % (root.slug, slugify(child_name)),
                defaults={"name": child_name, "parent": root, "position": child_position},
            )


def unseed(apps, schema_editor):
    Category = apps.get_model("catalog", "Category")
    Category.objects.filter(slug__in=[slugify(n) for n in DEFAULT_CATEGORIES]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(seed, unseed),
    ]
