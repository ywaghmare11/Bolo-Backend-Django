from datetime import timedelta

from django.db import transaction
from django.db.models import Case, Count, F, Q, When
from django.utils import timezone

from apps.comments.models import Comment
from apps.common.enums import TaskStatus
from apps.common.exceptions import NotFoundError
from apps.tasks.models import Task, VoiceRecording

SORT_ORDER = (
    Case(When(status=TaskStatus.OVERDUE, then=0), default=1),
    F("due_date").asc(nulls_last=True),
    "-created_at",
)


def _current_week_range():
    """Monday-Sunday, server-local day boundaries (matches api-spec.md's
    due_this_week semantics)."""
    today = timezone.localdate()
    start = today - timedelta(days=today.weekday())
    end = start + timedelta(days=6)
    return start, end


class TaskRepository:
    @staticmethod
    def _annotated_queryset(tenant_id):
        return (
            Task.objects.filter(tenant_id=tenant_id)
            .select_related("assigner", "assignee", "main_label")
            .annotate(
                subtask_count_annotated=Count("subtasks", distinct=True),
                done_subtask_count_annotated=Count(
                    "subtasks",
                    filter=Q(subtasks__status=TaskStatus.DONE_D),
                    distinct=True,
                ),
                comment_count_annotated=Count("comments", distinct=True),
            )
        )

    @staticmethod
    def create(**fields) -> Task:
        return Task.objects.create(**fields)

    @staticmethod
    def get_by_id(task_id, tenant_id) -> Task:
        try:
            return Task.objects.select_related(
                "assigner", "assignee", "main_label", "assignee_label",
            ).get(id=task_id, tenant_id=tenant_id)
        except Task.DoesNotExist:
            raise NotFoundError("Task", task_id) from None

    @staticmethod
    def get_subtask_by_id(subtask_id, parent_task_id, tenant_id) -> Task:
        """Validates the nested-route relationship (a subtask id under the wrong
        parent in the URL is treated as not found, not just forbidden)."""
        try:
            return Task.objects.select_related(
                "assigner", "assignee", "main_label", "assignee_label",
            ).get(id=subtask_id, parent_task_id=parent_task_id, tenant_id=tenant_id)
        except Task.DoesNotExist:
            raise NotFoundError("Subtask", subtask_id) from None

    @staticmethod
    def update(task: Task, **fields) -> Task:
        for key, value in fields.items():
            setattr(task, key, value)
        task.save()
        return task

    @staticmethod
    @transaction.atomic
    def delete(task: Task) -> None:
        """Explicitly clears children first rather than relying on the
        Comment/Evidence/parent_task PROTECT FKs staying vacuously empty --
        this phase never creates those rows, but Phase 3 will, and this
        needs zero rework once it does."""
        for subtask in task.subtasks.all():
            TaskRepository.delete(subtask)
        task.comments.all().delete()
        task.evidence.all().delete()
        task.delete()

    @staticmethod
    def list_assigned(user, tenant_id, label_id=None, is_archived=False):
        qs = (
            TaskRepository._annotated_queryset(tenant_id)
            .filter(assignee=user, is_archived=is_archived)
            .exclude(status__in=[TaskStatus.DRAFT, TaskStatus.DONE_D, TaskStatus.CANCELLED])
        )
        if label_id:
            qs = qs.filter(main_label_id=label_id)
        return qs.order_by(*SORT_ORDER)

    @staticmethod
    def list_delegated(user, tenant_id, label_id=None, is_archived=False):
        qs = (
            TaskRepository._annotated_queryset(tenant_id)
            .filter(assigner=user, is_archived=is_archived)
            .exclude(status=TaskStatus.DONE_D)
        )
        if label_id:
            qs = qs.filter(main_label_id=label_id)
        return qs.order_by(*SORT_ORDER)

    @staticmethod
    def list_needs_attention(user, tenant_id, label_id=None):
        qs = TaskRepository._annotated_queryset(tenant_id).filter(
            Q(assignee=user) | Q(assigner=user),
            status__in=[TaskStatus.OPEN, TaskStatus.OVERDUE, TaskStatus.DONE_A],
        )
        if label_id:
            qs = qs.filter(main_label_id=label_id)
        return qs.order_by(*SORT_ORDER)

    @staticmethod
    def list_by_status(user, tenant_id, status, label_id=None):
        """Backs the open/overdue/done_a views -- a single status, scoped to
        me as assignee or assigner, same shape as list_needs_attention with
        one status instead of three."""
        qs = TaskRepository._annotated_queryset(tenant_id).filter(
            Q(assignee=user) | Q(assigner=user), status=status,
        )
        if label_id:
            qs = qs.filter(main_label_id=label_id)
        return qs.order_by(*SORT_ORDER)

    @staticmethod
    def list_by_label(user, tenant_id, label_id):
        """main-label tasks (as assigner, or as assignee without a personal
        label override) + personal-label tasks (as assignee) -- api-spec.md's
        by_label semantics, distinct from the simple main_label_id filter the
        other views use."""
        qs = TaskRepository._annotated_queryset(tenant_id).filter(
            Q(assigner=user, main_label_id=label_id)
            | Q(assignee=user, main_label_id=label_id, assignee_label_id__isnull=True)
            | Q(assignee=user, assignee_label_id=label_id),
        )
        return qs.order_by(*SORT_ORDER)

    @staticmethod
    def list_due_this_week(user, tenant_id, label_id=None):
        start, end = _current_week_range()
        qs = (
            TaskRepository._annotated_queryset(tenant_id)
            .filter(Q(assignee=user) | Q(assigner=user), due_date__date__gte=start, due_date__date__lte=end)
            .exclude(status__in=[TaskStatus.DRAFT, TaskStatus.DONE_D, TaskStatus.CANCELLED])
        )
        if label_id:
            qs = qs.filter(main_label_id=label_id)
        return qs.order_by(*SORT_ORDER)

    @staticmethod
    def attach_latest_comments(tasks):
        """One extra DISTINCT ON query for the whole list, not N+1."""
        task_list = list(tasks)
        task_ids = [t.id for t in task_list]
        latest_comments = (
            Comment.objects.filter(task_id__in=task_ids)
            .select_related("author")
            .order_by("task_id", "-created_at")
            .distinct("task_id")
        )
        by_task_id = {c.task_id: c for c in latest_comments}
        for t in task_list:
            t.latest_comment_obj = by_task_id.get(t.id)
        return task_list

    @staticmethod
    def counts(user, tenant_id) -> dict:
        base = Task.objects.filter(tenant_id=tenant_id)
        assigned = (
            base.filter(assignee=user, is_archived=False)
            .exclude(status__in=[TaskStatus.DRAFT, TaskStatus.DONE_D, TaskStatus.CANCELLED])
            .count()
        )
        delegated = (
            base.filter(assigner=user, is_archived=False).exclude(status=TaskStatus.DONE_D).count()
        )
        needs_attention = base.filter(
            Q(assignee=user) | Q(assigner=user),
            status__in=[TaskStatus.OPEN, TaskStatus.OVERDUE, TaskStatus.DONE_A],
        ).count()
        mine = Q(assignee=user) | Q(assigner=user)
        open_count = base.filter(mine, status=TaskStatus.OPEN).count()
        overdue_count = base.filter(mine, status=TaskStatus.OVERDUE).count()
        done_a_count = base.filter(mine, status=TaskStatus.DONE_A).count()
        start, end = _current_week_range()
        due_this_week_count = (
            base.filter(mine, due_date__date__gte=start, due_date__date__lte=end)
            .exclude(status__in=[TaskStatus.DRAFT, TaskStatus.DONE_D, TaskStatus.CANCELLED])
            .count()
        )
        return {
            "assigned": assigned,
            "delegated": delegated,
            "needsAttention": needs_attention,
            "open": open_count,
            "overdue": overdue_count,
            "doneA": done_a_count,
            "dueThisWeek": due_this_week_count,
        }

    @staticmethod
    def subtask_count(task: Task) -> int:
        return task.subtasks.count()

    @staticmethod
    def done_subtask_count(task: Task) -> int:
        return task.subtasks.filter(status=TaskStatus.DONE_D).count()

    @staticmethod
    def comment_count(task: Task) -> int:
        return task.comments.count()

    @staticmethod
    def latest_comment(task: Task):
        return task.comments.select_related("author").order_by("-created_at").first()


class VoiceRecordingRepository:
    @staticmethod
    def create(**fields) -> VoiceRecording:
        return VoiceRecording.objects.create(**fields)

    @staticmethod
    def get_by_task_id(task_id, tenant_id) -> VoiceRecording:
        try:
            return VoiceRecording.objects.get(task_id=task_id, tenant_id=tenant_id)
        except VoiceRecording.DoesNotExist:
            raise NotFoundError("VoiceRecording", task_id) from None

    @staticmethod
    def update_audio_url(voice_recording: VoiceRecording, audio_url: str) -> VoiceRecording:
        voice_recording.audio_url = audio_url
        voice_recording.save()
        return voice_recording
