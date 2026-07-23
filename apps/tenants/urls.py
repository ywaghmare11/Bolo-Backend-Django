from django.urls import path

from apps.tenants.views import TenantOverviewView

urlpatterns = [
    path("", TenantOverviewView.as_view(), name="tenant-overview"),
]
