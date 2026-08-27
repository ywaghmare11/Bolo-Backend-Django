"""Phase 12 -- cache-aside for the per-user label list (GET /labels/mine and
/labels/shared share one cache entry, keyed by creator).
"""
import pytest
from rest_framework.test import APIClient

from apps.auth.tokens import issue_access_token
from apps.labels.models import ProjectLabel
from apps.labels.services import LabelService
from apps.users.factories import UserFactory


def _authed_client(user, tenant_id):
    client = APIClient()
    client.cookies["token"] = issue_access_token(user.id, tenant_id, "MID")
    return client


@pytest.mark.django_db
class TestLabelListCacheAside:
    def test_second_call_is_served_from_cache_with_no_queries(self, django_assert_num_queries):
        user = UserFactory()
        ProjectLabel.objects.create(tenant_id=user.tenant_id, created_by=user, name="NAAC")

        first = LabelService.list_my_labels(user, user.tenant_id)
        with django_assert_num_queries(0):
            second = LabelService.list_my_labels(user, user.tenant_id)
        assert [label.name for label in second] == [label.name for label in first] == ["NAAC"]

    def test_cache_is_scoped_to_the_creator(self):
        user = UserFactory()
        other = UserFactory(tenant=user.tenant)
        ProjectLabel.objects.create(tenant_id=user.tenant_id, created_by=user, name="Mine")
        ProjectLabel.objects.create(tenant_id=other.tenant_id, created_by=other, name="Theirs")

        assert [x.name for x in LabelService.list_my_labels(user, user.tenant_id)] == ["Mine"]
        assert [x.name for x in LabelService.list_my_labels(other, other.tenant_id)] == ["Theirs"]


@pytest.mark.django_db
class TestLabelListInvalidation:
    def test_create_busts_the_cache(self):
        user = UserFactory()
        assert LabelService.list_my_labels(user, user.tenant_id) == []

        LabelService.create_label(user, user.tenant_id, name="NAAC", color_code="#6B7280", description="")

        assert [x.name for x in LabelService.list_my_labels(user, user.tenant_id)] == ["NAAC"]

    def test_rename_busts_the_cache(self):
        user = UserFactory()
        label = LabelService.create_label(
            user, user.tenant_id, name="NAAC", color_code="#6B7280", description="",
        )
        LabelService.list_my_labels(user, user.tenant_id)  # warm

        LabelService.update_label(user, user.tenant_id, label.id, {"name": "NAAC Cycle 4"})

        assert [x.name for x in LabelService.list_my_labels(user, user.tenant_id)] == ["NAAC Cycle 4"]

    def test_delete_busts_the_cache(self):
        user = UserFactory()
        label = LabelService.create_label(
            user, user.tenant_id, name="Temp", color_code="#6B7280", description="",
        )
        LabelService.list_my_labels(user, user.tenant_id)  # warm

        LabelService.delete_label(user, user.tenant_id, label.id)

        assert LabelService.list_my_labels(user, user.tenant_id) == []

    def test_end_to_end_via_api(self):
        user = UserFactory()
        client = _authed_client(user, user.tenant_id)

        assert client.get("/api/v1/labels/mine/").data["data"] == []
        client.post("/api/v1/labels/", {"name": "GST-Q2"}, format="json")

        names = [row["name"] for row in client.get("/api/v1/labels/shared/").data["data"]]
        assert names == ["GST-Q2"]
