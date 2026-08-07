from apps.comments.repositories import CommentRepository
from apps.common.enums import NotificationType
from apps.common.exceptions import ForbiddenError
from apps.notifications.services import dispatch_notification
from apps.tasks.repositories import TaskRepository


def _get_accessible_task(tenant_id, task_id, user):
    task = TaskRepository.get_by_id(task_id, tenant_id)
    if user.id not in (task.assigner_id, task.assignee_id):
        raise ForbiddenError("You do not have access to this task")
    return task


class CommentService:
    @staticmethod
    def list_comments(user, tenant_id, task_id):
        _get_accessible_task(tenant_id, task_id, user)
        return CommentRepository.list_for_task(task_id)

    @staticmethod
    def create_comment(user, tenant_id, task_id, text):
        task = _get_accessible_task(tenant_id, task_id, user)
        comment = CommentRepository.create(task_id=task_id, author=user, text=text)

        other_party = task.assignee if user.id == task.assigner_id else task.assigner
        dispatch_notification(
            tenant_id=tenant_id,
            recipient=other_party,
            type_=NotificationType.TASK_COMMENTED,
            entity_type="task",
            entity_id=task.id,
            message=f"{user.name} commented on: {task.title}",
            actor_name=user.name,
            entity_title=task.title,
        )
        return comment

    @staticmethod
    def update_comment(user, tenant_id, task_id, comment_id, text):
        TaskRepository.get_by_id(task_id, tenant_id)  # 404s if the task isn't in this tenant
        comment = CommentRepository.get_by_id(comment_id, task_id)
        if comment.author_id != user.id:
            raise ForbiddenError("You are not the author of this comment")
        return CommentRepository.update(comment, text)

    @staticmethod
    def delete_comment(user, tenant_id, task_id, comment_id):
        TaskRepository.get_by_id(task_id, tenant_id)
        comment = CommentRepository.get_by_id(comment_id, task_id)
        if comment.author_id != user.id:
            raise ForbiddenError("You are not the author of this comment")
        CommentRepository.delete(comment)
