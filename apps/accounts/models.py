from django.conf import settings
from django.contrib.auth.models import AbstractUser, UserManager as DjangoUserManager
from django.core import signing
from django.db import models
from django.db.models import F, Q
from django.utils.translation import ugettext_lazy as _

from apps.core.models import TimeStampedModel

EMAIL_VERIFICATION_SALT = "accounts.email-verification"


class UserManager(DjangoUserManager):
    def sellers(self):
        return self.filter(is_seller=True, is_active=True)

    def create_with_temporary_password(self, username, email, **extra):
        password = self.make_random_password(length=14)
        user = self.create_user(username=username, email=email, password=password, **extra)
        return user, password


class User(AbstractUser):
    email = models.EmailField(_("email address"), unique=True)
    display_name = models.CharField(_("display name"), max_length=80, blank=True)
    phone = models.CharField(max_length=32, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)
    is_seller = models.BooleanField(default=False, help_text=_("Can open stores and list products."))
    email_verified = models.BooleanField(default=False)
    avatar = models.ImageField(upload_to="avatars/%Y/%m/", null=True, blank=True)

    objects = UserManager()

    REQUIRED_FIELDS = ["email"]

    class Meta:
        ordering = ("id",)
        index_together = [("is_seller", "is_active")]

    def __str__(self):
        return self.display_name or self.username

    @property
    def public_name(self):
        return self.display_name or self.get_full_name() or self.username

    def make_email_verification_token(self):
        signer = signing.TimestampSigner(settings.SECRET_KEY, ":", EMAIL_VERIFICATION_SALT)
        return signer.sign("%s:%s" % (self.pk, self.email))

    @classmethod
    def from_email_verification_token(cls, token, max_age=60 * 60 * 48):
        signer = signing.TimestampSigner(settings.SECRET_KEY, ":", EMAIL_VERIFICATION_SALT)
        value = signer.unsign(token, max_age=max_age)
        pk, email = value.split(":", 1)
        return cls.objects.get(pk=pk, email=email)


class Profile(TimeStampedModel):
    class Currency(models.TextChoices):
        USD = "USD", "US Dollar"
        EUR = "EUR", "Euro"
        GBP = "GBP", "Pound Sterling"
        CAD = "CAD", "Canadian Dollar"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    bio = models.TextField(blank=True, max_length=2000)
    website = models.URLField(blank=True)
    location = models.CharField(max_length=120, blank=True)
    preferred_currency = models.CharField(max_length=3, choices=Currency.choices, default=Currency.USD)
    timezone = models.CharField(max_length=64, default="UTC")
    # None = user has never answered the marketing consent prompt.
    marketing_opt_in = models.NullBooleanField(_("marketing opt-in"))
    social_links = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ("id",)

    def __str__(self):
        return "Profile<%s>" % self.user_id


class Address(TimeStampedModel):
    class Kind(models.TextChoices):
        SHIPPING = "shipping", _("Shipping")
        BILLING = "billing", _("Billing")

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="addresses")
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.SHIPPING)
    label = models.CharField(max_length=40, blank=True)
    full_name = models.CharField(max_length=120)
    line1 = models.CharField(max_length=200)
    line2 = models.CharField(max_length=200, blank=True)
    city = models.CharField(max_length=100)
    region = models.CharField(max_length=100, blank=True)
    postal_code = models.CharField(max_length=20)
    country = models.CharField(max_length=2, help_text="ISO 3166-1 alpha-2")
    phone = models.CharField(max_length=32, blank=True)
    is_default = models.BooleanField(default=False)

    class Meta:
        ordering = ("-is_default", "id")
        verbose_name_plural = "addresses"
        constraints = [
            models.UniqueConstraint(
                fields=("user", "kind"),
                condition=Q(is_default=True),
                name="accounts_address_one_default_per_kind",
            ),
        ]

    def __str__(self):
        return "%s, %s %s" % (self.line1, self.city, self.country)

    def one_line(self):
        parts = [self.line1, self.line2, self.city, self.region, self.postal_code, self.country]
        return ", ".join(p for p in parts if p)


class Follow(TimeStampedModel):
    follower = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="following_set")
    followee = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="follower_set")
    notify = models.BooleanField(default=True, help_text=_("Notify follower about followee's new products."))

    class Meta:
        ordering = ("-created_at",)
        unique_together = ("follower", "followee")
        constraints = [
            models.CheckConstraint(check=~Q(follower=F("followee")), name="accounts_follow_not_self"),
        ]

    def __str__(self):
        return "%s -> %s" % (self.follower_id, self.followee_id)
