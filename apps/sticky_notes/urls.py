from django.urls import path

from apps.sticky_notes.views import (
    StickyNoteDetailView,
    StickyNoteListCreateView,
    StickyNotePromoteView,
)

urlpatterns = [
    path("", StickyNoteListCreateView.as_view(), name="sticky-note-list-create"),
    path("<uuid:note_id>/", StickyNoteDetailView.as_view(), name="sticky-note-detail"),
    path("<uuid:note_id>/promote/", StickyNotePromoteView.as_view(), name="sticky-note-promote"),
]
