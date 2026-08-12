from django.urls import path

from apps.broadcasts.views import (
    BroadcastAckCountView,
    BroadcastAckView,
    BroadcastDetailView,
    BroadcastImageView,
    BroadcastListCreateView,
    BroadcastPublishView,
)

urlpatterns = [
    path("", BroadcastListCreateView.as_view(), name="broadcast-list-create"),
    path("<uuid:broadcast_id>/", BroadcastDetailView.as_view(), name="broadcast-detail"),
    path("<uuid:broadcast_id>/publish/", BroadcastPublishView.as_view(), name="broadcast-publish"),
    path("<uuid:broadcast_id>/image/", BroadcastImageView.as_view(), name="broadcast-image"),
    path("<uuid:broadcast_id>/ack/", BroadcastAckView.as_view(), name="broadcast-ack"),
    path(
        "<uuid:broadcast_id>/ack-count/",
        BroadcastAckCountView.as_view(),
        name="broadcast-ack-count",
    ),
]
