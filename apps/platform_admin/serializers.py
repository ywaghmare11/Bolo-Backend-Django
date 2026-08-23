from rest_framework import serializers

from apps.common.enums import Language, OrgRoleLevel, Vertical


class CreateTenantSerializer(serializers.Serializer):
    tenantName = serializers.CharField(max_length=255)
    urlSlug = serializers.CharField(max_length=40)
    vertical = serializers.ChoiceField(choices=Vertical.choices)
    adminName = serializers.CharField(max_length=255)
    adminEmail = serializers.EmailField()
    adminPhone = serializers.CharField(max_length=32, required=False, allow_null=True, allow_blank=True)
    roleLabel = serializers.CharField(max_length=100, required=False, allow_null=True, allow_blank=True)
    preferredLang = serializers.ChoiceField(choices=Language.choices, required=False, default=Language.EN)


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
        "createdAt": tenant.created_at.isoformat(),
        "memberCount": tenant.member_count_annotated,
        "departmentCount": tenant.dept_count_annotated,
    }


def serialize_added_member(user) -> dict:
    return {"userId": str(user.id), "email": user.email}
