from celery import shared_task
from django.utils import timezone

from apps.common.enums import NotificationType
from apps.notifications.services import dispatch_notification
from apps.sticky_notes.models import StickyNote

RETENTION_WINDOW_DAYS = 3


@shared_task(name="apps.sticky_notes.retention_sweep")
def sticky_note_retention_sweep():
    """Hard-deletes StickyNote rows whose dueAt is more than 3 days in the past.

    Natural Django/Celery-beat port of upstream's stickyNoteRetentionSweep.job.ts
    24h setInterval (docs/architecture/domain-model.md's StickyNote section, PRD §5.6).
    """
    cutoff = timezone.now() - timezone.timedelta(days=RETENTION_WINDOW_DAYS)
    StickyNote.objects.filter(due_at__lt=cutoff).delete()


@shared_task(name="apps.sticky_notes.reminder_sweep")
def sticky_note_reminder_sweep():
    """EventBridge-equivalent sweep for REMINDER_FIRED (domain-model.md's W30 note:
    "EventBridge fires REMINDER_FIRED notification for notes where dueAt <= NOW()").
    One-shot per note, guarded by StickyNote.reminder_fired -- fires once, in-app only
    (no email channel for this type, per api-spec.md §11's Channel column), and never
    refires even if the note stays overdue until the retention sweep eventually deletes it.
    """
    notes = StickyNote.objects.filter(
        due_at__isnull=False, due_at__lte=timezone.now(), reminder_fired=False,
    ).select_related("user")
    for note in notes:
        dispatch_notification(
            tenant_id=note.user.tenant_id,
            recipient=note.user,
            type_=NotificationType.REMINDER_FIRED,
            entity_type="sticky_note",
            entity_id=note.id,
            message=f"Reminder: {note.text}",
            entity_title=note.text,
        )
        note.reminder_fired = True
        note.save(update_fields=["reminder_fired"])
