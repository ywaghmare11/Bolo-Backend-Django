from celery import shared_task


@shared_task(name="apps.common.write_audit_log")
def write_audit_log_task(
    *, tenant_id, actor_id, entity_type, entity_id, action, before, after,
    actor_type=None, metadata=None,
):
    """Fire-and-forget write for apps/common/audit_middleware.py -- never blocks the
    request/response cycle it was dispatched from. See CLAUDE.md Architecture Rules
    point 8: logged on failure, never rolls back or blocks the parent request.

    actor_type/metadata are passed explicitly only for the PlatformAdmin routes
    (a PlatformAdmin isn't a User row, so actor_id is null and its identity lives
    in metadata). When actor_type is omitted the row falls back to the original
    USER/SYSTEM inference from whether actor_id is present."""
    from apps.audit.models import AuditLog
    from apps.common.enums import AuditActorType

    resolved_actor_type = actor_type or (
        AuditActorType.SYSTEM if actor_id is None else AuditActorType.USER
    )
    AuditLog.objects.create(
        tenant_id=tenant_id,
        actor_id=actor_id,
        actor_type=resolved_actor_type,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        before=before,
        after=after,
        metadata=metadata,
    )
