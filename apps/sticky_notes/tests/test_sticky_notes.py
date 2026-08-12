from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.auth.tokens import issue_access_token
from apps.notifications.models import Notification
from apps.sticky_notes.models import StickyNote
from apps.sticky_notes.tasks import sticky_note_reminder_sweep, sticky_note_retention_sweep
from apps.tenants.factories import TenantFactory
from apps.users.factories import UserFactory


def _authed_client(user, tenant_id, role_level="MID"):
    client = APIClient()
    client.cookies["token"] = issue_access_token(user.id, tenant_id, role_level)
    return client


@pytest.fixture
def tenant():
    return TenantFactory()


@pytest.fixture
def owner(tenant):
    return UserFactory(tenant=tenant)


@pytest.fixture
def other_user(tenant):
    return UserFactory(tenant=tenant)


@pytest.fixture
def client(owner, tenant):
    return _authed_client(owner, tenant.id)


@pytest.mark.django_db
class TestStickyNoteCreate:
    def test_create_defaults(self, client, owner):
        resp = client.post("/api/v1/sticky-notes/", {"text": "Buy milk"}, format="json")
        assert resp.status_code == 201
        data = resp.data["data"]
        assert data["text"] == "Buy milk"
        assert data["colorCode"] == "#FEF3C7"
        assert data["isPinned"] is False
        assert data["dueAt"] is None
        assert data["promotedToTaskId"] is None

        note = StickyNote.objects.get(id=data["id"])
        assert note.user_id == owner.id

    def test_create_with_due_at_and_pinned(self, client):
        resp = client.post(
            "/api/v1/sticky-notes/",
            {"text": "Prepare agenda", "dueAt": "2026-09-01T09:00:00Z", "isPinned": True},
            format="json",
        )
        assert resp.status_code == 201
        data = resp.data["data"]
        assert data["isPinned"] is True
        assert data["dueAt"] is not None

    def test_create_rejects_invalid_color_code(self, client):
        resp = client.post(
            "/api/v1/sticky-notes/", {"text": "x", "colorCode": "not-a-color"}, format="json",
        )
        assert resp.status_code == 400

    def test_create_requires_text(self, client):
        resp = client.post("/api/v1/sticky-notes/", {}, format="json")
        assert resp.status_code == 400


@pytest.mark.django_db
class TestStickyNoteList:
    def test_list_only_returns_own_notes(self, client, owner, other_user, tenant):
        StickyNote.objects.create(user=owner, text="mine")
        StickyNote.objects.create(user=other_user, text="not mine")

        resp = client.get("/api/v1/sticky-notes/")
        assert resp.status_code == 200
        texts = [n["text"] for n in resp.data["data"]]
        assert texts == ["mine"]
        assert resp.data["pagination"]["total"] == 1

    def test_list_sort_order(self, client, owner):
        now = timezone.now()
        unpinned_no_due = StickyNote.objects.create(user=owner, text="unpinned no due")
        pinned = StickyNote.objects.create(user=owner, text="pinned", is_pinned=True)
        unpinned_due_soon = StickyNote.objects.create(
            user=owner, text="due soon", due_at=now + timedelta(days=1),
        )

        resp = client.get("/api/v1/sticky-notes/")
        texts = [n["text"] for n in resp.data["data"]]
        assert texts == [pinned.text, unpinned_due_soon.text, unpinned_no_due.text]


@pytest.mark.django_db
class TestStickyNoteDetail:
    def test_get_owned_note(self, client, owner):
        note = StickyNote.objects.create(user=owner, text="hi")
        resp = client.get(f"/api/v1/sticky-notes/{note.id}/")
        assert resp.status_code == 200
        assert resp.data["data"]["id"] == str(note.id)

    def test_get_other_users_note_is_404(self, client, other_user):
        note = StickyNote.objects.create(user=other_user, text="hi")
        resp = client.get(f"/api/v1/sticky-notes/{note.id}/")
        assert resp.status_code == 404


@pytest.mark.django_db
class TestStickyNoteUpdate:
    def test_patch_updates_fields(self, client, owner):
        note = StickyNote.objects.create(user=owner, text="old")
        resp = client.patch(
            f"/api/v1/sticky-notes/{note.id}/", {"text": "new", "isPinned": True}, format="json",
        )
        assert resp.status_code == 200
        note.refresh_from_db()
        assert note.text == "new"
        assert note.is_pinned is True

    def test_patch_other_users_note_is_404(self, client, other_user):
        note = StickyNote.objects.create(user=other_user, text="hi")
        resp = client.patch(f"/api/v1/sticky-notes/{note.id}/", {"text": "new"}, format="json")
        assert resp.status_code == 404

    def test_patch_empty_body_rejected(self, client, owner):
        note = StickyNote.objects.create(user=owner, text="hi")
        resp = client.patch(f"/api/v1/sticky-notes/{note.id}/", {}, format="json")
        assert resp.status_code == 400


@pytest.mark.django_db
class TestStickyNoteDelete:
    def test_delete_owned_note(self, client, owner):
        note = StickyNote.objects.create(user=owner, text="hi")
        resp = client.delete(f"/api/v1/sticky-notes/{note.id}/")
        assert resp.status_code == 200
        assert not StickyNote.objects.filter(id=note.id).exists()

    def test_delete_other_users_note_is_404(self, client, other_user):
        note = StickyNote.objects.create(user=other_user, text="hi")
        resp = client.delete(f"/api/v1/sticky-notes/{note.id}/")
        assert resp.status_code == 404
        assert StickyNote.objects.filter(id=note.id).exists()


@pytest.mark.django_db
class TestStickyNotePromote:
    def test_promote_creates_task(self, client, owner, other_user):
        note = StickyNote.objects.create(user=owner, text="Prepare agenda")
        resp = client.post(
            f"/api/v1/sticky-notes/{note.id}/promote/",
            {"assigneeId": str(other_user.id), "dueDate": "2026-09-01T09:00:00Z"},
            format="json",
        )
        assert resp.status_code == 201
        assert resp.data["data"]["status"] == "OPEN"

        note.refresh_from_db()
        assert str(note.promoted_to_task_id) == resp.data["data"]["taskId"]

    def test_promote_without_due_date_saves_draft(self, client, owner, other_user):
        note = StickyNote.objects.create(user=owner, text="Prepare agenda")
        resp = client.post(
            f"/api/v1/sticky-notes/{note.id}/promote/",
            {"assigneeId": str(other_user.id)},
            format="json",
        )
        assert resp.status_code == 201
        assert resp.data["data"]["status"] == "DRAFT"

    def test_promote_twice_is_conflict(self, client, owner, other_user):
        note = StickyNote.objects.create(user=owner, text="Prepare agenda")
        client.post(
            f"/api/v1/sticky-notes/{note.id}/promote/",
            {"assigneeId": str(other_user.id)},
            format="json",
        )
        resp = client.post(
            f"/api/v1/sticky-notes/{note.id}/promote/",
            {"assigneeId": str(other_user.id)},
            format="json",
        )
        assert resp.status_code == 409
        assert resp.data["error"]["code"] == "ALREADY_PROMOTED"

    def test_promote_other_users_note_is_404(self, client, other_user):
        note = StickyNote.objects.create(user=other_user, text="hi")
        resp = client.post(
            f"/api/v1/sticky-notes/{note.id}/promote/",
            {"assigneeId": str(other_user.id)},
            format="json",
        )
        assert resp.status_code == 404


@pytest.mark.django_db
class TestStickyNoteRetentionSweep:
    def test_sweep_deletes_notes_past_retention_window(self, owner):
        now = timezone.now()
        old = StickyNote.objects.create(user=owner, text="old", due_at=now - timedelta(days=4))
        recent = StickyNote.objects.create(user=owner, text="recent", due_at=now - timedelta(days=1))
        no_due = StickyNote.objects.create(user=owner, text="no due")

        sticky_note_retention_sweep()

        remaining_ids = set(StickyNote.objects.values_list("id", flat=True))
        assert old.id not in remaining_ids
        assert recent.id in remaining_ids
        assert no_due.id in remaining_ids


@pytest.mark.django_db
class TestStickyNoteReminderSweep:
    def test_fires_once_for_note_past_due(self, owner):
        note = StickyNote.objects.create(
            user=owner, text="Call vendor", due_at=timezone.now() - timedelta(minutes=5),
        )
        sticky_note_reminder_sweep()

        note.refresh_from_db()
        assert note.reminder_fired is True
        assert Notification.objects.filter(type="REMINDER_FIRED", recipient=owner).count() == 1

    def test_does_not_refire_on_second_run(self, owner):
        StickyNote.objects.create(
            user=owner, text="Call vendor", due_at=timezone.now() - timedelta(minutes=5),
        )
        sticky_note_reminder_sweep()
        sticky_note_reminder_sweep()

        assert Notification.objects.filter(type="REMINDER_FIRED").count() == 1

    def test_note_not_yet_due_is_untouched(self, owner):
        note = StickyNote.objects.create(
            user=owner, text="Future note", due_at=timezone.now() + timedelta(days=1),
        )
        sticky_note_reminder_sweep()

        note.refresh_from_db()
        assert note.reminder_fired is False
        assert not Notification.objects.filter(type="REMINDER_FIRED").exists()

    def test_note_without_due_at_is_untouched(self, owner):
        note = StickyNote.objects.create(user=owner, text="No due date")
        sticky_note_reminder_sweep()

        note.refresh_from_db()
        assert note.reminder_fired is False
