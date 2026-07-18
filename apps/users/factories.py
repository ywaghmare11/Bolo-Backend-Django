import factory

from apps.common.enums import Language
from apps.users.models import User


class UserFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = User

    tenant = factory.SubFactory("apps.tenants.factories.TenantFactory")
    name = factory.Sequence(lambda n: f"Test User {n}")
    email = factory.Sequence(lambda n: f"user{n}@example.com")
    preferred_lang = Language.EN
