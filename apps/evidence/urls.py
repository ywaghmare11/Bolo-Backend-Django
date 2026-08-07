from django.urls import path

from apps.evidence.views import EvidenceDetailView, EvidenceFileView, EvidenceListCreateView

urlpatterns = [
    path("<uuid:task_id>/evidence/", EvidenceListCreateView.as_view(), name="evidence-list-create"),
    path(
        "<uuid:task_id>/evidence/<uuid:evidence_id>/file/",
        EvidenceFileView.as_view(),
        name="evidence-file",
    ),
    path(
        "<uuid:task_id>/evidence/<uuid:evidence_id>/",
        EvidenceDetailView.as_view(),
        name="evidence-detail",
    ),
]
