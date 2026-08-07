from apps.comments.models import Comment
from apps.common.exceptions import NotFoundError


class CommentRepository:
    @staticmethod
    def list_for_task(task_id):
        return Comment.objects.filter(task_id=task_id).select_related("author").order_by("created_at")

    @staticmethod
    def create(task_id, author, text) -> Comment:
        return Comment.objects.create(task_id=task_id, author=author, text=text)

    @staticmethod
    def get_by_id(comment_id, task_id) -> Comment:
        try:
            return Comment.objects.select_related("author").get(id=comment_id, task_id=task_id)
        except Comment.DoesNotExist:
            raise NotFoundError("Comment", comment_id) from None

    @staticmethod
    def update(comment: Comment, text: str) -> Comment:
        comment.text = text
        comment.is_edited = True
        comment.save()
        return comment

    @staticmethod
    def delete(comment: Comment) -> None:
        comment.delete()
