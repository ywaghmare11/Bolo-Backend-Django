from rest_framework import serializers

from apps.common.enums import Language, OrgRoleLevel, TenantStatus, Vertical


class CreateTenantSerializer(serializers.Serializer):
    tenantName = serializers.CharField(max_length=255)
    urlSlug = serializers.CharField(max_length=40)
    vertical = serializers.ChoiceField(choices=Vertical.choices)
    adminName = serializers.CharField(max_length=255)
    adminEmail = serializers.EmailField()
    adminPhone = serializers.CharField(max_length=32, required=False, allow_null=True, allow_blank=True)
    roleLabel = serializers.CharField(max_length=100, required=False, allow_null=True, allow_blank=True)
    preferredLang = serializers.ChoiceField(choices=Language.choices, required=False, default=Language.EN)


class UpdateTenantSerializer(serializers.Serializer):
    """PATCH /platform-admin/tenants/:id -- operator offboarding (Phase 15e).
    Only the lifecycle status is mutable here; name/vertical/slug are set once
    at creation."""

    status = serializers.ChoiceField(choices=TenantStatus.choices)
    reason = serializers.CharField(
        max_length=255, required=False, allow_blank=True, allow_null=True,
    )


class AddMemberSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=255)
    email = serializers.EmailField()
    roleLevel = serializers.ChoiceField(choices=OrgRoleLevel.choices)
    roleLabel = serializers.CharField(max_length=100, required=False, allow_null=True, allow_blank=True)
    departmentId = serializers.UUIDField(required=False, allow_null=True)
    phone = serializers.CharField(max_length=32, required=False, allow_null=True, allow_blank=True)


def serialize_tenant_created(tenant, admin_user, role_label) -> dict:
    return {
        "tenantId": str(tenant.id),
        "tenantName": tenant.name,
        "urlSlug": tenant.url_slug,
        "vertical": tenant.vertical,
        "createdAt": tenant.created_at.isoformat(),
        "admin": {
            "userId": str(admin_user.id),
            "name": admin_user.name,
            "email": admin_user.email,
            "roleLevel": OrgRoleLevel.TOP,
            "roleLabel": role_label,
        },
    }


def serialize_tenant_list_item(tenant) -> dict:
    return {
        "tenantId": str(tenant.id),
        "name": tenant.name,
        "vertical": tenant.vertical,
        "status": tenant.status,
        "createdAt": tenant.created_at.isoformat(),
        "memberCount": tenant.member_count_annotated,
        "departmentCount": tenant.dept_count_annotated,
    }


def serialize_tenant_detail(tenant) -> dict:
    return {
        "tenantId": str(tenant.id),
        "name": tenant.name,
        "vertical": tenant.vertical,
        "urlSlug": tenant.url_slug,
        "status": tenant.status,
        "suspendedAt": tenant.suspended_at.isoformat() if tenant.suspended_at else None,
        "suspensionReason": tenant.suspension_reason,
        "createdAt": tenant.created_at.isoformat(),
    }


def serialize_added_member(user) -> dict:
    return {"userId": str(user.id), "email": user.email}


def serialize_member(membership) -> dict:
    """One row of a tenant's member table (GET .../tenants/:id/members/, Phase 15d).
    `user` and `department` are select_related'd by MembershipRepository.list_for_tenant."""
    return {
        "userId": str(membership.user_id),
        "name": membership.user.name,
        "email": membership.user.email,
        "roleLevel": membership.role_level,
        "roleLabel": membership.role_label,
        "departmentName": membership.department.name if membership.department_id else None,
        "canBroadcast": membership.can_broadcast,
        "joinedAt": membership.joined_at.isoformat(),
    }


def serialize_admin_identity(admin) -> dict:
    """The PlatformAdmin's own identity -- returned by verify-otp and GET
    /platform-admin/auth/me (the SPA route guard's session check, Phase 15d)."""
    return {
        "adminId": str(admin.id),
        "name": admin.name,
        "email": admin.email,
        "role": admin.role,
    }
