from celery import shared_task
from django.utils import timezone

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
