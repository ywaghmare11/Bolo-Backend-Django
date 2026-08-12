from django.urls import path

from apps.search.views import SearchStickiesView, SearchTasksView

urlpatterns = [
    path("tasks/", SearchTasksView.as_view(), name="search-tasks"),
    path("stickies/", SearchStickiesView.as_view(), name="search-stickies"),
]
