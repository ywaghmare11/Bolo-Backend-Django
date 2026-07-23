def serialize_tenant_overview(tenant) -> dict:
    return {
        "id": str(tenant.id),
        "name": tenant.name,
        "vertical": tenant.vertical,
        "memberCount": tenant.member_count_annotated,
        "deptCount": tenant.dept_count_annotated,
        "createdAt": tenant.created_at.isoformat(),
    }
