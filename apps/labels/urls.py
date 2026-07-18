from django.urls import path

from apps.labels.views import LabelCreateView, MyLabelsView, SharedLabelsView

urlpatterns = [
    path("", LabelCreateView.as_view(), name="label-create"),
    path("shared/", SharedLabelsView.as_view(), name="label-shared"),
    path("mine/", MyLabelsView.as_view(), name="label-mine"),
]
