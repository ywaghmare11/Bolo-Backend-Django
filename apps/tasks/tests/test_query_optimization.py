"""Regression test for Phase 3's query-optimization claim (ROADMAP.md Phase 3/11):
the task list endpoint must not grow its query count as the number of tasks grows.
TaskRepository._annotated_queryset already covers this with select_related
(assigner/assignee/main_label) + annotate(Count(...)) for subtask/comment counts,
and attach_latest_comments does one bulk query instead of one-per-row -- this test
locks that in so a future change can't quietly reintroduce an N+1.
"""
import pytest
from rest_framework.test import APIClient

from apps.auth.tokens import issue_access_token
from apps.tasks.factories import TaskFactory
from apps.tenants.factories import TenantFactory
from apps.users.factories import UserFactory


def _authed_client(user, tenant_id):
    client = APIClient()
    client.cookies["token"] = issue_access_token(user.id, tenant_id, "MID")
    return client


@pytest.mark.django_db
def test_task_list_query_count_does_not_scale_with_row_count(django_assert_num_queries):
    tenant = TenantFactory()
    assigner = UserFactory(tenant=tenant)
    assignee = UserFactory(tenant=tenant)
    client = _authed_client(assigner, tenant.id)

    TaskFactory.create_batch(3, tenant_id=tenant.id, assigner=assigner, assignee=assignee)

    with django_assert_num_queries(4):
        resp = client.get("/api/v1/tasks/?view=delegated")
    assert resp.status_code == 200
    assert len(resp.data["data"]) == 3

    TaskFactory.create_batch(5, tenant_id=tenant.id, assigner=assigner, assignee=assignee)

    with django_assert_num_queries(4):
        resp = client.get("/api/v1/tasks/?view=delegated")
    assert resp.status_code == 200
    assert len(resp.data["data"]) == 8
