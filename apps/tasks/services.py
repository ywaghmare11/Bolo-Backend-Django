from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from apps.common import caching
from apps.common.enums import AcceptanceStatus, NotificationType, TaskStatus
from apps.common.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationError
from apps.labels.repositories import LabelRepository
from apps.labels.services import LabelService
from apps.notifications.services import dispatch_notification
from apps.tasks.ai_extract import extract_fields
from apps.tasks.repositories import TaskRepository, VoiceRecordingRepository
from apps.users.repositories import UserRepository


def _validate_same_tenant_assignee(assignee_id, tenant_id):
    try:
        assignee = UserRepository.get_by_id(assignee_id)
    except NotFoundError:
        raise ValidationError("assigneeId must belong to the same tenant") from None
    if str(assignee.tenant_id) != str(tenant_id):
        raise ValidationError("assigneeId must belong to the same tenant")
    return assignee


def _validate_owned_label(label_id, user, tenant_id):
    if label_id is None:
        return
    if LabelRepository.get_owned_by(label_id, user, tenant_id) is None:
        raise ValidationError("mainLabelId is invalid")


class TaskService:
    @staticmethod
    def create_task(
        user, tenant_id, title, assignee_id, due_date, priority, main_label_id, description,
        evidence_required=False, voice_recording=None,
    ):
        assignee = _validate_same_tenant_assignee(assignee_id, tenant_id)
        _validate_owned_label(main_label_id, user, tenant_id)

        status = TaskStatus.OPEN if due_date else TaskStatus.DRAFT

        # tasks row + voice_recordings row (transcript only) in one transaction --
        # api-spec.md §2 requires this; audio itself is a separate S3 upload after
        # the response is returned, never inside this transaction.
        with transaction.atomic():
            task = TaskRepository.create(
                tenant_id=tenant_id,
                title=title,
                assigner=user,
                assignee=assignee,
                status=status,
                priority=priority,
                due_date=due_date,
                description=description,
                main_label_id=main_label_id,
                evidence_required=evidence_required,
            )
            if voice_recording is not None:
                VoiceRecordingRepository.create(
                    tenant_id=tenant_id,
                    task=task,
                    raw_transcript=voice_recording["raw_transcript"],
                    language=voice_recording.get("language"),
                    duration_secs=voice_recording.get("duration_secs"),
                    confidence_score=voice_recording.get("confidence_score"),
                )

        if status == TaskStatus.OPEN:
            dispatch_notification(
                tenant_id=tenant_id,
                recipient=assignee,
                type_=NotificationType.TASK_ASSIGNED,
                entity_type="task",
                entity_id=task.id,
                message=f"{user.name} assigned you a task: {task.title}",
                actor_name=user.name,
                entity_title=task.title,
            )
        caching.bust_task_counts(tenant_id, user.id, assignee.id)
        return task

    @staticmethod
    def update_task(user, tenant_id, task_id, fields: dict):
        task = TaskRepository.get_by_id(task_id, tenant_id)
        if task.assigner_id != user.id:
            raise ForbiddenError("You are not the assigner of this task")

        previous_assignee_id = task.assignee_id
        update_fields = {}

        if "assignee_id" in fields:
            if task.subtasks.exists():
                raise ConflictError(
                    "Cannot reassign -- this task has existing subtasks", code="REASSIGN_BLOCKED",
                )
            new_assignee = _validate_same_tenant_assignee(fields["assignee_id"], tenant_id)
            update_fields["assignee"] = new_assignee
            update_fields["assignee_label"] = None  # cleared on reassignment

        if "main_label_id" in fields:
            _validate_owned_label(fields["main_label_id"], user, tenant_id)
            update_fields["main_label_id"] = fields["main_label_id"]

        if "priority" in fields:
            update_fields["priority"] = fields["priority"]
        if "description" in fields:
            update_fields["description"] = fields["description"]
        if "evidence_required" in fields:
            update_fields["evidence_required"] = fields["evidence_required"]

        if "due_date" in fields:
            new_due_date = fields["due_date"]
            update_fields["due_date"] = new_due_date
            # A new due date is a genuinely new threshold to cross -- the daily sweep's
            # one-shot guards (apps/tasks/tasks.py) no longer apply to the old one.
            update_fields["due_today_notified_at"] = None
            update_fields["due_tomorrow_notified_at"] = None

            if new_due_date is None and task.status == TaskStatus.OPEN:
                update_fields["status"] = TaskStatus.DRAFT
            elif (
                new_due_date is not None
                and task.status == TaskStatus.OVERDUE
                and new_due_date.date() >= timezone.localdate()
            ):
                # CLAUDE.md Business Rules: "An OVERDUE task auto-transitions back to
                # OPEN/IN_PROGRESS if its due date is edited to today-or-later."
                update_fields["status"] = (
                    TaskStatus.IN_PROGRESS
                    if task.acceptance_status == AcceptanceStatus.ACCEPTED
                    else TaskStatus.OPEN
                )

        task = TaskRepository.update(task, **update_fields)

        is_subtask = task.parent_task_id is not None
        dispatch_notification(
            tenant_id=tenant_id,
            recipient=task.assignee,
            type_=NotificationType.SUBTASK_EDITED if is_subtask else NotificationType.TASK_EDITED,
            entity_type="task",
            entity_id=task.id,
            message=f"{user.name} edited the {'subtask' if is_subtask else 'task'}: {task.title}",
            actor_name=user.name,
            entity_title=task.title,
        )
        caching.bust_task_counts(
            tenant_id, task.assigner_id, task.assignee_id, previous_assignee_id,
        )
        return task

    @staticmethod
    def delete_task(user, tenant_id, task_id):
        task = TaskRepository.get_by_id(task_id, tenant_id)
        if task.assigner_id != user.id:
            raise ForbiddenError("You are not the assigner of this task")
        if task.status == TaskStatus.DONE_D:
            raise ConflictError("Task is already completed and archived", code="TASK_TERMINAL")
        # A delete cascades to every subtask (TaskRepository.delete), so the
        # subtask participants' counts change too, not just the parent's.
        affected_user_ids = {task.assigner_id, task.assignee_id}
        for sub_assigner_id, sub_assignee_id in task.subtasks.values_list(
            "assigner_id", "assignee_id",
        ):
            affected_user_ids.update((sub_assigner_id, sub_assignee_id))
        TaskRepository.delete(task)
        caching.bust_task_counts(tenant_id, *affected_user_ids)

    @staticmethod
    def accept_task(user, tenant_id, task_id):
        task = TaskRepository.get_by_id(task_id, tenant_id)
        if task.assignee_id != user.id:
            raise ForbiddenError("You are not the assignee of this task")
        if task.status != TaskStatus.OPEN:
            raise ValidationError("Task must be OPEN to accept")

        task.status = TaskStatus.IN_PROGRESS
        task.acceptance_status = AcceptanceStatus.ACCEPTED
        task.accepted_at = timezone.now()
        task.save()

        dispatch_notification(
            tenant_id=tenant_id,
            recipient=task.assigner,
            type_=NotificationType.TASK_ACCEPTED,
            entity_type="task",
            entity_id=task.id,
            message=f"{user.name} accepted the task: {task.title}",
            actor_name=user.name,
            entity_title=task.title,
        )
        caching.bust_task_counts(tenant_id, task.assigner_id, task.assignee_id)
        return task

    @staticmethod
    def mark_done_a(user, tenant_id, task_id):
        task = TaskRepository.get_by_id(task_id, tenant_id)
        if task.assignee_id != user.id:
            raise ForbiddenError("You are not the assignee of this task")
        if task.status not in (TaskStatus.IN_PROGRESS, TaskStatus.OVERDUE):
            raise ValidationError("Task must be in progress to mark complete")
        if task.evidence_required and not task.evidence.exists():
            raise ValidationError(
                "At least one evidence file must be uploaded before marking this task complete",
                code="EVIDENCE_REQUIRED",
            )

        task.status = TaskStatus.DONE_A
        task.save()

        is_subtask = task.parent_task_id is not None
        dispatch_notification(
            tenant_id=tenant_id,
            recipient=task.assigner,
            type_=NotificationType.SUBTASK_DONE_A if is_subtask else NotificationType.TASK_DONE_A,
            entity_type="task",
            entity_id=task.id,
            message=f"{user.name} marked the {'subtask' if is_subtask else 'task'} complete: {task.title}",
            actor_name=user.name,
            entity_title=task.title,
        )
        caching.bust_task_counts(tenant_id, task.assigner_id, task.assignee_id)
        return task

    @staticmethod
    def mark_done_d(user, tenant_id, task_id):
        task = TaskRepository.get_by_id(task_id, tenant_id)
        if task.assigner_id != user.id:
            raise ForbiddenError("You are not the assigner of this task")
        if task.status not in (TaskStatus.IN_PROGRESS, TaskStatus.OVERDUE, TaskStatus.DONE_A):
            raise ValidationError("Task is not ready to be marked done")
        # A CANCELLED subtask can never itself reach DONE_D, so it must count as
        # resolved here too -- otherwise a single cancelled subtask would permanently
        # block the parent from ever completing (upstream fix, notIn not just != DONE_D).
        if task.subtasks.exclude(status__in=[TaskStatus.DONE_D, TaskStatus.CANCELLED]).exists():
            raise ConflictError(
                "All subtasks must be DONE_D or CANCELLED before the parent task can be completed",
                code="SUBTASKS_INCOMPLETE",
            )

        is_subtask = task.parent_task_id is not None
        task.status = TaskStatus.DONE_D
        # Archiving only ever applies to a main task -- a subtask reaching DONE_D
        # doesn't archive anything (only the assigner's explicit done-d on the main
        # task does, and only once every subtask is itself resolved).
        if not is_subtask:
            task.is_archived = True
        task.save()

        dispatch_notification(
            tenant_id=tenant_id,
            recipient=task.assignee,
            type_=NotificationType.SUBTASK_DONE_D if is_subtask else NotificationType.TASK_DONE_D,
            entity_type="task",
            entity_id=task.id,
            message=(
                f"{user.name} marked the subtask done: {task.title}"
                if is_subtask
                else f"{user.name} archived the task: {task.title}"
            ),
            actor_name=user.name,
            entity_title=task.title,
        )
        caching.bust_task_counts(tenant_id, task.assigner_id, task.assignee_id)
        return task

    @staticmethod
    def cancel_task(user, tenant_id, task_id):
        task = TaskRepository.get_by_id(task_id, tenant_id)
        if task.assigner_id != user.id:
            raise ForbiddenError("You are not the assigner of this task")
        if task.status == TaskStatus.DONE_D:
            raise ConflictError("Task is already completed and archived", code="TASK_TERMINAL")

        was_draft = task.status == TaskStatus.DRAFT
        task.status = TaskStatus.CANCELLED
        task.save()

        affected_user_ids = {task.assigner_id, task.assignee_id}
        for subtask in task.subtasks.exclude(status=TaskStatus.DONE_D):
            subtask.status = TaskStatus.CANCELLED
            subtask.save()
            affected_user_ids.update((subtask.assigner_id, subtask.assignee_id))
        caching.bust_task_counts(tenant_id, *affected_user_ids)

        if not was_draft:
            dispatch_notification(
                tenant_id=tenant_id,
                recipient=task.assignee,
                type_=NotificationType.TASK_CANCELLED,
                entity_type="task",
                entity_id=task.id,
                message=f"{user.name} cancelled the task: {task.title}",
                actor_name=user.name,
                entity_title=task.title,
            )
        return task

    @staticmethod
    def create_subtask(
        user, tenant_id, parent_task_id, title, assignee_id, due_date, priority, description,
        main_label_id=None,
    ):
        parent = TaskRepository.get_by_id(parent_task_id, tenant_id)
        if parent.assignee_id != user.id:
            raise ForbiddenError("You are not the assignee of the parent task")
        if parent.status != TaskStatus.IN_PROGRESS:
            raise ValidationError("Parent task must be accepted before adding subtasks")
        if str(assignee_id) == str(parent.assigner_id):
            raise ValidationError(
                "A subtask cannot be assigned back to the parent task's assigner",
                code="ASSIGNMENT_LOOP",
            )
        if due_date >= parent.due_date:
            raise ValidationError(
                "Subtask due date must be earlier than the parent task's due date",
                code="SUBTASK_DUE_DATE_INVALID",
            )

        assignee = _validate_same_tenant_assignee(assignee_id, tenant_id)
        if main_label_id is not None:
            _validate_owned_label(main_label_id, user, tenant_id)
            effective_label_id = main_label_id
        else:
            # Silent inheritance from the parent -- not re-validated against the
            # caller's own label ownership, since it wasn't the caller's choice.
            effective_label_id = parent.main_label_id

        subtask = TaskRepository.create(
            tenant_id=tenant_id,
            title=title,
            assigner=user,  # the parent task's assignee acts as the subtask's assigner
            assignee=assignee,
            status=TaskStatus.OPEN,  # dueDate is required for subtasks, unlike a top-level task
            priority=priority,
            due_date=due_date,
            description=description,
            main_label_id=effective_label_id,
            parent_task=parent,
        )

        # Fires to the *parent's* assigner, not the new sub-assignee -- keeps the
        # original delegator aware that a subtask was spawned under a task they
        # delegated (api-spec.md §11 notification-types table, SUBTASK_CREATED row).
        dispatch_notification(
            tenant_id=tenant_id,
            recipient=parent.assigner,
            type_=NotificationType.SUBTASK_CREATED,
            entity_type="task",
            entity_id=subtask.id,
            message=f'{user.name} created a subtask under "{parent.title}": {subtask.title}',
            actor_name=user.name,
            entity_title=subtask.title,
        )
        # The new subtask is a fresh OPEN row for its assigner (the parent's
        # assignee) and its assignee -- the parent's own assigner has no new row.
        caching.bust_task_counts(tenant_id, subtask.assigner_id, subtask.assignee_id)
        return subtask

    @staticmethod
    def get_subtask_or_404(tenant_id, parent_task_id, subtask_id):
        return TaskRepository.get_subtask_by_id(subtask_id, parent_task_id, tenant_id)

    @staticmethod
    def remind_task(user, tenant_id, task_id):
        task = TaskRepository.get_by_id(task_id, tenant_id)
        if task.assigner_id != user.id:
            raise ForbiddenError("You are not the assigner of this task")
        if task.status not in (TaskStatus.OPEN, TaskStatus.IN_PROGRESS, TaskStatus.OVERDUE):
            raise ValidationError("Task is not in a state that can be reminded")

        dispatch_notification(
            tenant_id=tenant_id,
            recipient=task.assignee,
            type_=NotificationType.TASK_REMINDER,
            entity_type="task",
            entity_id=task.id,
            message=f"Reminder from {user.name}: {task.title}",
            actor_name=user.name,
            entity_title=task.title,
            send_email=True,
            email_subject=f"Reminder: {task.title}",
            email_body=f"{user.name} sent you a reminder about: {task.title}",
        )

    @staticmethod
    def get_task_detail(user, tenant_id, task_id):
        task = TaskRepository.get_by_id(task_id, tenant_id)
        if user.id not in (task.assigner_id, task.assignee_id):
            raise ForbiddenError("You do not have access to this task")
        my_personal_labels = LabelService.list_my_labels(user, tenant_id)
        return {"task": task, "my_personal_labels": my_personal_labels}

    @staticmethod
    def list_tasks(user, tenant_id, view, label_id=None, is_archived=False):
        if view == "assigned":
            qs = TaskRepository.list_assigned(user, tenant_id, label_id, is_archived)
        elif view == "delegated":
            qs = TaskRepository.list_delegated(user, tenant_id, label_id, is_archived)
        elif view == "needs_attention":
            qs = TaskRepository.list_needs_attention(user, tenant_id, label_id)
        elif view == "open":
            qs = TaskRepository.list_by_status(user, tenant_id, TaskStatus.OPEN, label_id)
        elif view == "overdue":
            qs = TaskRepository.list_by_status(user, tenant_id, TaskStatus.OVERDUE, label_id)
        elif view == "done_a":
            qs = TaskRepository.list_by_status(user, tenant_id, TaskStatus.DONE_A, label_id)
        elif view == "by_label":
            if not label_id:
                raise ValidationError("labelId is required for view=by_label")
            qs = TaskRepository.list_by_label(user, tenant_id, label_id)
        elif view == "due_this_week":
            qs = TaskRepository.list_due_this_week(user, tenant_id, label_id)
        else:
            raise ValidationError(
                "Invalid view -- must be assigned, delegated, needs_attention, open, "
                "overdue, done_a, by_label, or due_this_week",
            )
        return qs

    @staticmethod
    def get_counts(user, tenant_id):
        """Cache-aside (ROADMAP.md Phase 12): the tab badge counts are read on
        nearly every page load and recomputed from a handful of COUNTs. Every
        task write path in this service calls caching.bust_task_counts() for the
        affected users; the TTL is only a backstop for a missed bust."""
        key = caching.task_counts_key(tenant_id, user.id)
        cached = cache.get(key)
        if cached is not None:
            return cached
        counts = TaskRepository.counts(user, tenant_id)
        cache.set(key, counts, caching.TASK_COUNTS_TTL)
        return counts

    @staticmethod
    def attach_latest_comments(tasks):
        return TaskRepository.attach_latest_comments(tasks)

    @staticmethod
    def extract_task_fields(text):
        return extract_fields(text)
