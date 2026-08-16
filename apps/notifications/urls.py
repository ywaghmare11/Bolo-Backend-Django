from django.urls import path

from apps.notifications.views import NudgeFeedView, NudgeSkipAllView, NudgeSkipView

urlpatterns = [
    path("", NudgeFeedView.as_view(), name="nudge-feed"),
    path("skip-all/", NudgeSkipAllView.as_view(), name="nudge-skip-all"),
    path("<uuid:notification_id>/skip/", NudgeSkipView.as_view(), name="nudge-skip"),
]
