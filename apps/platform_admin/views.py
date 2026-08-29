from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from apps.auth.serializers import RequestOtpSerializer, VerifyOtpSerializer
from apps.common.enums import PlatformAdminRole
from apps.common.exceptions import ValidationError
from apps.common.permissions import AllowAny, HasPlatformAdminRole, IsAuthenticated
from apps.common.responses import success_response
from apps.platform_admin.authentication import PlatformAdminCookieJWTAuthentication
from apps.platform_admin.serializers import (
    AddMemberSerializer,
    CreateTenantSerializer,
    UpdateTenantSerializer,
    serialize_added_member,
    serialize_tenant_created,
    serialize_tenant_detail,
    serialize_tenant_list_item,
)
from apps.platform_admin.services import PlatformAdminAuthService, PlatformAdminTenantService
from apps.platform_admin.tokens import clear_admin_auth_cookie, set_admin_auth_cookie


class PlatformAdminRequestOtpView(APIView):
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "otp_request"

    def post(self, request):
        serializer = RequestOtpSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]

        PlatformAdminAuthService.request_otp(email)
        return success_response(None, f"OTP sent to {email}")


class PlatformAdminVerifyOtpView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = VerifyOtpSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = PlatformAdminAuthService.verify_otp(
            serializer.validated_data["email"], serializer.validated_data["otp"],
        )
        admin = result["admin"]

        response = success_response(
            {"adminId": str(admin.id), "name": admin.name, "email": admin.email},
            "Login successful",
        )
        set_admin_auth_cookie(response, result["access_token"])
        return response


class PlatformAdminLogoutView(APIView):
    """No server-side session state to revoke (single JWT, no refresh table) --
    see apps/platform_admin/tokens.py. Clearing the cookie is the whole thing."""

    authentication_classes = [PlatformAdminCookieJWTAuthentication]
    # Not role-gated on purpose: any authenticated admin (whatever their
    # PlatformAdminRole) must be able to end their own session.
    permission_classes = [IsAuthenticated]

    def post(self, request):
        response = success_response(None, "Logged out")
        clear_admin_auth_cookie(response)
        return response


class PlatformAdminTenantListCreateView(APIView):
    authentication_classes = [PlatformAdminCookieJWTAuthentication]
    permission_classes = [IsAuthenticated, HasPlatformAdminRole([PlatformAdminRole.SUPER_ADMIN])]

    def get(self, request):
        tenants = PlatformAdminTenantService.list_tenants()
        return success_response([serialize_tenant_list_item(t) for t in tenants], "OK")

    def post(self, request):
        serializer = CreateTenantSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        result = PlatformAdminTenantService.create_tenant(
            tenant_name=d["tenantName"],
            url_slug=d["urlSlug"],
            vertical=d["vertical"],
            admin_name=d["adminName"],
            admin_email=d["adminEmail"],
            admin_phone=d.get("adminPhone"),
            role_label=d.get("roleLabel"),
            preferred_lang=d.get("preferredLang", "EN"),
        )
        data = serialize_tenant_created(result["tenant"], result["admin_user"], result["role_label"])
        return success_response(data, "Tenant registered", status=201)


class PlatformAdminTenantDetailView(APIView):
    """PATCH /platform-admin/tenants/:tenantId -- operator offboarding
    (ROADMAP.md Phase 15e). Suspend / reactivate a whole tenant. No DELETE:
    a hard purge is a separate, export-first step (W58), not built here."""

    authentication_classes = [PlatformAdminCookieJWTAuthentication]
    permission_classes = [IsAuthenticated, HasPlatformAdminRole([PlatformAdminRole.SUPER_ADMIN])]

    def patch(self, request, tenant_id):
        serializer = UpdateTenantSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        tenant = PlatformAdminTenantService.set_tenant_status(
            tenant_id, status=d["status"], reason=d.get("reason"),
        )
        return success_response(serialize_tenant_detail(tenant), "Tenant updated")


class PlatformAdminTenantMembersView(APIView):
    authentication_classes = [PlatformAdminCookieJWTAuthentication]
    permission_classes = [IsAuthenticated, HasPlatformAdminRole([PlatformAdminRole.SUPER_ADMIN])]

    def post(self, request, tenant_id):
        serializer = AddMemberSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        d = serializer.validated_data

        user = PlatformAdminTenantService.add_member(
            tenant_id,
            name=d["name"],
            email=d["email"],
            role_level=d["roleLevel"],
            role_label=d.get("roleLabel"),
            department_id=d.get("departmentId"),
            phone=d.get("phone"),
        )
        return success_response(serialize_added_member(user), "Member added", status=201)


class PlatformAdminTenantMemberDetailView(APIView):
    authentication_classes = [PlatformAdminCookieJWTAuthentication]
    permission_classes = [IsAuthenticated, HasPlatformAdminRole([PlatformAdminRole.SUPER_ADMIN])]

    def delete(self, request, tenant_id, user_id):
        PlatformAdminTenantService.remove_member(tenant_id, user_id)
        return success_response(None, "Member removed")


class PlatformAdminMemberImportView(APIView):
    """Multi-format bulk member import (ROADMAP.md Phase 15c) -- multipart upload
    of a single `file` (.xlsx / .csv / .json). The ETL pipeline lives in
    apps/platform_admin/etl.py; the Load step is in the service."""

    MAX_UPLOAD_BYTES = 5 * 1024 * 1024

    authentication_classes = [PlatformAdminCookieJWTAuthentication]
    permission_classes = [IsAuthenticated, HasPlatformAdminRole([PlatformAdminRole.SUPER_ADMIN])]

    def post(self, request, tenant_id):
        file_obj = request.FILES.get("file")
        if file_obj is None:
            raise ValidationError("Attach a file as multipart field 'file'.", code="INVALID_FILE")
        if file_obj.size > self.MAX_UPLOAD_BYTES:
            raise ValidationError(
                f"File is too large ({file_obj.size} bytes); the limit is "
                f"{self.MAX_UPLOAD_BYTES} bytes.",
                code="INVALID_FILE",
            )

        result = PlatformAdminTenantService.bulk_import_members(
            tenant_id, file_obj.read(), file_obj.name,
        )
        return success_response(result, "Import complete")
