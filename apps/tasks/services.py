from django.utils import timezone

from apps.common.enums import AcceptanceStatus, NotificationType, TaskStatus
from apps.common.exceptions import ConflictError, ForbiddenError, NotFoundError, ValidationError
from apps.labels.repositories import LabelRepository
from apps.labels.services import LabelService
from apps.notifications.services import dispatch_notification
from apps.tasks.repositories import TaskRepository
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
    def create_task(user, tenant_id, title, assignee_id, due_date, priority, main_label_id, description):
        assignee = _validate_same_tenant_assignee(assignee_id, tenant_id)
        _validate_owned_label(main_label_id, user, tenant_id)

        status = TaskStatus.OPEN if due_date else TaskStatus.DRAFT

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
        return task

    @staticmethod
    def update_task(user, tenant_id, task_id, fields: dict):
        task = TaskRepository.get_by_id(task_id, tenant_id)
        if task.assigner_id != user.id:
            raise ForbiddenError("You are not the assigner of this task")

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

        if "due_date" in fields:
            update_fields["due_date"] = fields["due_date"]
            if fields["due_date"] is None and task.status == TaskStatus.OPEN:
                update_fields["status"] = TaskStatus.DRAFT

        task = TaskRepository.update(task, **update_fields)

        dispatch_notification(
            tenant_id=tenant_id,
            recipient=task.assignee,
            type_=NotificationType.TASK_EDITED,
            entity_type="task",
            entity_id=task.id,
            message=f"{user.name} edited the task: {task.title}",
            actor_name=user.name,
            entity_title=task.title,
        )
        return task

    @staticmethod
    def delete_task(user, tenant_id, task_id):
        task = TaskRepository.get_by_id(task_id, tenant_id)
        if task.assigner_id != user.id:
            raise ForbiddenError("You are not the assigner of this task")
        if task.status == TaskStatus.DONE_D:
            raise ConflictError("Task is already completed and archived", code="TASK_TERMINAL")
        TaskRepository.delete(task)

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
        return task

    @staticmethod
    def mark_done_a(user, tenant_id, task_id):
        task = TaskRepository.get_by_id(task_id, tenant_id)
        if task.assignee_id != user.id:
            raise ForbiddenError("You are not the assignee of this task")
        if task.status not in (TaskStatus.IN_PROGRESS, TaskStatus.OVERDUE):
            raise ValidationError("Task must be in progress to mark complete")

        task.status = TaskStatus.DONE_A
        task.save()

        dispatch_notification(
            tenant_id=tenant_id,
            recipient=task.assigner,
            type_=NotificationType.TASK_DONE_A,
            entity_type="task",
            entity_id=task.id,
            message=f"{user.name} marked the task complete: {task.title}",
            actor_name=user.name,
            entity_title=task.title,
        )
        return task

    @staticmethod
    def mark_done_d(user, tenant_id, task_id):
        task = TaskRepository.get_by_id(task_id, tenant_id)
        if task.assigner_id != user.id:
            raise ForbiddenError("You are not the assigner of this task")
        if task.status not in (TaskStatus.IN_PROGRESS, TaskStatus.OVERDUE, TaskStatus.DONE_A):
            raise ValidationError("Task is not ready to be marked done")
        if task.subtasks.exclude(status=TaskStatus.DONE_D).exists():
            raise ConflictError(
                "All subtasks must be DONE_D before the parent task can be completed",
                code="SUBTASKS_INCOMPLETE",
            )

        task.status = TaskStatus.DONE_D
        task.is_archived = True
        task.save()

        dispatch_notification(
            tenant_id=tenant_id,
            recipient=task.assignee,
            type_=NotificationType.TASK_DONE_D,
            entity_type="task",
            entity_id=task.id,
            message=f"{user.name} archived the task: {task.title}",
            actor_name=user.name,
            entity_title=task.title,
        )
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

        for subtask in task.subtasks.exclude(status=TaskStatus.DONE_D):
            subtask.status = TaskStatus.CANCELLED
            subtask.save()

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
        else:
            raise ValidationError("Invalid view -- must be assigned, delegated, or needs_attention")
        return qs

    @staticmethod
    def get_counts(user, tenant_id):
        return TaskRepository.counts(user, tenant_id)

    @staticmethod
    def attach_latest_comments(tasks):
        return TaskRepository.attach_latest_comments(tasks)
