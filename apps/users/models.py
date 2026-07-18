from django.db import models

from apps.common.enums import Language
from apps.common.models import TimestampedModel


class User(TimestampedModel):
    tenant = models.ForeignKey(
        "tenants.Tenant", on_delete=models.PROTECT, related_name="users",
    )
    name = models.CharField(max_length=255)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=32, null=True, blank=True)
    # S3 object key -- pre-signed GET URL generated per request, mirrors Evidence.file_url
    profile_pic_url = models.CharField(max_length=512, null=True, blank=True)
    preferred_lang = models.CharField(
        max_length=2, choices=Language.choices, default=Language.EN,
    )
    # session-tracking fields; also what the audit middleware's login/logout
    # exception keys USER_LOGIN/USER_LOGOUT off of (no direct audit call)
    last_login_at = models.DateTimeField(null=True, blank=True)
    last_logout_at = models.DateTimeField(null=True, blank=True)

    # User doesn't extend AbstractUser/AbstractBaseUser (not Django's
    # contrib.auth model) -- these two attributes are the minimal shim DRF's
    # IsAuthenticated permission and auth internals expect on request.user.
    is_authenticated = True
    is_anonymous = False

    class Meta:
        db_table = "users"

    def __str__(self):
        return self.email
