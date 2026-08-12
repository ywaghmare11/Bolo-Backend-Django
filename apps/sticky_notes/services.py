from apps.common.enums import Priority
from apps.common.exceptions import ConflictError, ValidationError
from apps.sticky_notes.repositories import StickyNoteRepository
from apps.tasks.services import TaskService


class StickyNoteService:
    @staticmethod
    def list_notes(user):
        return StickyNoteRepository.list_for_user(user)

    @staticmethod
    def create_note(user, text, due_at, is_pinned, color_code):
        return StickyNoteRepository.create(
            user=user, text=text, due_at=due_at, is_pinned=is_pinned, color_code=color_code,
        )

    @staticmethod
    def get_note(user, note_id):
        return StickyNoteRepository.get_owned_by_or_404(note_id, user)

    @staticmethod
    def update_note(user, note_id, fields: dict):
        if not fields:
            raise ValidationError("At least one field must be provided")
        note = StickyNoteRepository.get_owned_by_or_404(note_id, user)
        return StickyNoteRepository.update(note, **fields)

    @staticmethod
    def delete_note(user, note_id):
        note = StickyNoteRepository.get_owned_by_or_404(note_id, user)
        StickyNoteRepository.delete(note)

    @staticmethod
    def promote_to_task(user, tenant_id, note_id, assignee_id, due_date):
        note = StickyNoteRepository.get_owned_by_or_404(note_id, user)
        if note.promoted_to_task_id is not None:
            raise ConflictError("Sticky note already promoted to a task", code="ALREADY_PROMOTED")

        task = TaskService.create_task(
            user=user,
            tenant_id=tenant_id,
            title=note.text,
            assignee_id=assignee_id,
            due_date=due_date,
            priority=Priority.P3,
            main_label_id=None,
            description="",
        )
        StickyNoteRepository.set_promoted_task(note, task)
        return task
