from django.urls import path

from apps.platform_admin.views import (
    PlatformAdminLogoutView,
    PlatformAdminMemberImportView,
    PlatformAdminMeView,
    PlatformAdminRequestOtpView,
    PlatformAdminTenantDetailView,
    PlatformAdminTenantListCreateView,
    PlatformAdminTenantMemberDetailView,
    PlatformAdminTenantMembersView,
    PlatformAdminVerifyOtpView,
)

urlpatterns = [
    path("auth/request-otp/", PlatformAdminRequestOtpView.as_view(), name="platform-admin-request-otp"),
    path("auth/verify-otp/", PlatformAdminVerifyOtpView.as_view(), name="platform-admin-verify-otp"),
    path("auth/me/", PlatformAdminMeView.as_view(), name="platform-admin-me"),
    path("auth/logout/", PlatformAdminLogoutView.as_view(), name="platform-admin-logout"),
    path("tenants/", PlatformAdminTenantListCreateView.as_view(), name="platform-admin-tenants"),
    path(
        "tenants/<uuid:tenant_id>/",
        PlatformAdminTenantDetailView.as_view(),
        name="platform-admin-tenant-detail",
    ),
    path(
        "tenants/<uuid:tenant_id>/members/",
        PlatformAdminTenantMembersView.as_view(),
        name="platform-admin-tenant-members",
    ),
    path(
        "tenants/<uuid:tenant_id>/members/import/",
        PlatformAdminMemberImportView.as_view(),
        name="platform-admin-tenant-member-import",
    ),
    path(
        "tenants/<uuid:tenant_id>/members/<uuid:user_id>/",
        PlatformAdminTenantMemberDetailView.as_view(),
        name="platform-admin-tenant-member-detail",
    ),
]
