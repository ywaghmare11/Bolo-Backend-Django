from django.urls import path

from apps.tasks.views import (
    TaskAcceptView,
    TaskCancelView,
    TaskCountsView,
    TaskDetailView,
    TaskDoneAView,
    TaskDoneDView,
    TaskListCreateView,
    TaskRemindView,
)

urlpatterns = [
    path("", TaskListCreateView.as_view(), name="task-list-create"),
    path("counts/", TaskCountsView.as_view(), name="task-counts"),
    path("<uuid:task_id>/", TaskDetailView.as_view(), name="task-detail"),
    path("<uuid:task_id>/accept/", TaskAcceptView.as_view(), name="task-accept"),
    path("<uuid:task_id>/done-a/", TaskDoneAView.as_view(), name="task-done-a"),
    path("<uuid:task_id>/done-d/", TaskDoneDView.as_view(), name="task-done-d"),
    path("<uuid:task_id>/cancel/", TaskCancelView.as_view(), name="task-cancel"),
    path("<uuid:task_id>/remind/", TaskRemindView.as_view(), name="task-remind"),
]
