import factory

from apps.tasks.models import Task


class TaskFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Task

    title = factory.Sequence(lambda n: f"Test Task {n}")
    assigner = factory.SubFactory("apps.users.factories.UserFactory")
    assignee = factory.SubFactory("apps.users.factories.UserFactory")
    tenant_id = factory.SelfAttribute("assigner.tenant_id")
