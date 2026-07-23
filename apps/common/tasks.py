from celery import shared_task


@shared_task(name="apps.common.write_audit_log")
def write_audit_log_task(*, tenant_id, actor_id, entity_type, entity_id, action, before, after):
    """Fire-and-forget write for apps/common/audit_middleware.py -- never blocks the
    request/response cycle it was dispatched from. See CLAUDE.md Architecture Rules
    point 8: logged on failure, never rolls back or blocks the parent request."""
    from apps.audit.models import AuditLog
    from apps.common.enums import AuditActorType

    AuditLog.objects.create(
        tenant_id=tenant_id,
        actor_id=actor_id,
        actor_type=AuditActorType.SYSTEM if actor_id is None else AuditActorType.USER,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        before=before,
        after=after,
    )
