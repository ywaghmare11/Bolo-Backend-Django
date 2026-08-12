from django.db.models import Case, F, IntegerField, Value, When

from apps.common.exceptions import NotFoundError
from apps.sticky_notes.models import StickyNote

# Pinned first -> dueAt ascending (nulls last) -> createdAt DESC (api-spec.md §9).
SORT_ORDER = (
    Case(When(is_pinned=True, then=Value(0)), default=Value(1), output_field=IntegerField()),
    F("due_at").asc(nulls_last=True),
    "-created_at",
)


class StickyNoteRepository:
    @staticmethod
    def list_for_user(user):
        return StickyNote.objects.filter(user=user).order_by(*SORT_ORDER)

    @staticmethod
    def create(**fields) -> StickyNote:
        return StickyNote.objects.create(**fields)

    @staticmethod
    def get_owned_by_or_404(note_id, user) -> StickyNote:
        note = StickyNote.objects.filter(id=note_id, user=user).first()
        if note is None:
            raise NotFoundError("StickyNote", note_id)
        return note

    @staticmethod
    def update(note: StickyNote, **fields) -> StickyNote:
        for key, value in fields.items():
            setattr(note, key, value)
        note.save()
        return note

    @staticmethod
    def delete(note: StickyNote) -> None:
        note.delete()

    @staticmethod
    def set_promoted_task(note: StickyNote, task) -> StickyNote:
        note.promoted_to_task = task
        note.save(update_fields=["promoted_to_task", "updated_at"])
        return note
