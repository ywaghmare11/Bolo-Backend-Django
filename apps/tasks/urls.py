from django.urls import path

from apps.tasks.views import (
    SubtaskAcceptView,
    SubtaskCancelView,
    SubtaskDetailView,
    SubtaskDoneAView,
    SubtaskDoneDView,
    SubtaskListCreateView,
    TaskAcceptView,
    TaskCancelView,
    TaskCountsView,
    TaskDetailView,
    TaskDoneAView,
    TaskDoneDView,
    TaskExtractView,
    TaskListCreateView,
    TaskRemindView,
    VoiceRecordingAudioView,
    VoiceRecordingDetailView,
)

urlpatterns = [
    path("", TaskListCreateView.as_view(), name="task-list-create"),
    path("counts/", TaskCountsView.as_view(), name="task-counts"),
    path("extract/", TaskExtractView.as_view(), name="task-extract"),
    path("<uuid:task_id>/", TaskDetailView.as_view(), name="task-detail"),
    path("<uuid:task_id>/accept/", TaskAcceptView.as_view(), name="task-accept"),
    path("<uuid:task_id>/done-a/", TaskDoneAView.as_view(), name="task-done-a"),
    path("<uuid:task_id>/done-d/", TaskDoneDView.as_view(), name="task-done-d"),
    path("<uuid:task_id>/cancel/", TaskCancelView.as_view(), name="task-cancel"),
    path("<uuid:task_id>/remind/", TaskRemindView.as_view(), name="task-remind"),
    path("<uuid:task_id>/subtasks/", SubtaskListCreateView.as_view(), name="subtask-create"),
    path(
        "<uuid:task_id>/subtasks/<uuid:subtask_id>/",
        SubtaskDetailView.as_view(),
        name="subtask-detail",
    ),
    path(
        "<uuid:task_id>/subtasks/<uuid:subtask_id>/accept/",
        SubtaskAcceptView.as_view(),
        name="subtask-accept",
    ),
    path(
        "<uuid:task_id>/subtasks/<uuid:subtask_id>/done-a/",
        SubtaskDoneAView.as_view(),
        name="subtask-done-a",
    ),
    path(
        "<uuid:task_id>/subtasks/<uuid:subtask_id>/done-d/",
        SubtaskDoneDView.as_view(),
        name="subtask-done-d",
    ),
    path(
        "<uuid:task_id>/subtasks/<uuid:subtask_id>/cancel/",
        SubtaskCancelView.as_view(),
        name="subtask-cancel",
    ),
    path(
        "<uuid:task_id>/voice-recording/",
        VoiceRecordingDetailView.as_view(),
        name="voice-recording-detail",
    ),
    path(
        "<uuid:task_id>/voice-recording/audio/",
        VoiceRecordingAudioView.as_view(),
        name="voice-recording-audio",
    ),
]
