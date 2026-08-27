"""Regression tests for Phase 3's query-optimization claim (ROADMAP.md Phase 3/11):
neither the task *list* nor the task *detail* endpoint may grow its query count as
the number of related rows grows -- this is the "proof-of-work for Phase 3's
optimization claims" Phase 11 asks for, on both endpoints it names.

- List: TaskRepository._annotated_queryset covers it with select_related
  (assigner/assignee/main_label) + annotate(Count(...)) for subtask/comment counts,
  and attach_latest_comments does one bulk query instead of one-per-row.
- Detail: TaskRepository.get_by_id select_relates the FK chain and
  TaskDetailSerializer select_relates each of subtasks/comments/evidence, so the
  count is flat regardless of how many of each a task carries.
"""
from datetime import timedelta

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework.test import APIClient

from apps.auth.tokens import issue_access_token
from apps.comments.models import Comment
from apps.common.enums import EvidenceType, TaskStatus
from apps.evidence.models import Evidence
from apps.tasks.factories import TaskFactory
from apps.tasks.models import Task
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


@pytest.mark.django_db
def test_task_detail_query_count_does_not_scale_with_related_row_count(django_assert_num_queries):
    """GET /tasks/:id/ serializes subtasks + comments + evidence inline -- its
    query count must stay flat as each of those grows, or the detail page is an
    N+1 waiting to happen the moment a task gets busy."""
    tenant = TenantFactory()
    assigner = UserFactory(tenant=tenant)
    assignee = UserFactory(tenant=tenant)
    client = _authed_client(assigner, tenant.id)

    parent = TaskFactory(
        tenant_id=tenant.id, assigner=assigner, assignee=assignee,
        status=TaskStatus.IN_PROGRESS, due_date=timezone.now() + timedelta(days=10),
    )

    def _add_related(n):
        for _ in range(n):
            Task.objects.create(
                tenant_id=tenant.id, title="Subtask", assigner=assignee, assignee=assigner,
                status=TaskStatus.OPEN, due_date=timezone.now() + timedelta(days=1),
                parent_task=parent,
            )
            Comment.objects.create(task=parent, author=assigner, text="progress note")
            Evidence.objects.create(
                task=parent, uploader=assignee, file_url="t/e/report.pdf",
                file_name="report.pdf", file_size=1024, file_type=EvidenceType.PDF,
            )

    _add_related(1)
    # One warm-up call so the per-user label list (cached, see Phase 12) is
    # already populated -- we're measuring steady state, not the cold-cache miss.
    assert client.get(f"/api/v1/tasks/{parent.id}/").status_code == 200
    with CaptureQueriesContext(connection) as ctx:
        resp = client.get(f"/api/v1/tasks/{parent.id}/")
    assert resp.status_code == 200
    baseline = len(ctx.captured_queries)

    _add_related(4)
    with django_assert_num_queries(baseline):
        resp = client.get(f"/api/v1/tasks/{parent.id}/")
    assert resp.status_code == 200
    assert len(resp.data["data"]["subtasks"]) == 5
    assert len(resp.data["data"]["comments"]) == 5
    assert len(resp.data["data"]["evidence"]) == 5
