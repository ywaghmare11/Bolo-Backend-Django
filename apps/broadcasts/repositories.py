from django.db import IntegrityError
from django.db.models import Count, Exists, OuterRef, Q
from django.utils import timezone

from apps.broadcasts.models import (
    BroadcastAcknowledgement,
    BroadcastNotice,
    BroadcastNoticeAudienceDept,
    BroadcastNoticeAudienceRoleLevel,
)
from apps.common.enums import BroadcastStatus
from apps.common.exceptions import ConflictError, NotFoundError
from apps.tenants.models import Department, TenantMembership


class BroadcastRepository:
    @staticmethod
    def _base_queryset():
        return BroadcastNotice.objects.select_related("sender").prefetch_related(
            "audience_depts__department", "audience_role_levels",
        )

    @staticmethod
    def create(**fields) -> BroadcastNotice:
        return BroadcastNotice.objects.create(**fields)

    @staticmethod
    def get_by_id_or_404(broadcast_id, tenant_id) -> BroadcastNotice:
        try:
            return BroadcastRepository._base_queryset().get(id=broadcast_id, tenant_id=tenant_id)
        except BroadcastNotice.DoesNotExist:
            raise NotFoundError("BroadcastNotice", broadcast_id) from None

    @staticmethod
    def update(broadcast: BroadcastNotice, **fields) -> BroadcastNotice:
        for key, value in fields.items():
            setattr(broadcast, key, value)
        broadcast.save()
        return broadcast

    @staticmethod
    def delete(broadcast: BroadcastNotice) -> None:
        broadcast.delete()

    @staticmethod
    def set_audience(broadcast: BroadcastNotice, dept_ids, role_levels) -> None:
        BroadcastNoticeAudienceDept.objects.filter(broadcast=broadcast).delete()
        BroadcastNoticeAudienceRoleLevel.objects.filter(broadcast=broadcast).delete()
        BroadcastNoticeAudienceDept.objects.bulk_create(
            [BroadcastNoticeAudienceDept(broadcast=broadcast, department_id=d) for d in dept_ids],
        )
        BroadcastNoticeAudienceRoleLevel.objects.bulk_create(
            [BroadcastNoticeAudienceRoleLevel(broadcast=broadcast, role_level=r) for r in role_levels],
        )

    @staticmethod
    def department_ids_belong_to_tenant(tenant_id, dept_ids) -> bool:
        if not dept_ids:
            return True
        found = Department.objects.filter(tenant_id=tenant_id, id__in=dept_ids).count()
        return found == len(set(dept_ids))

    @staticmethod
    def _annotate_common(qs, caller_id=None):
        # No distinct=True -- BroadcastAcknowledgement's composite PK (broadcast, user)
        # can't be used as a COUNT(DISTINCT ...) target, and nothing else in this
        # queryset joins in a way that would double-count acknowledgement rows anyway.
        qs = qs.annotate(ack_count_annotated=Count("acknowledgements"))
        if caller_id is not None:
            qs = qs.annotate(
                has_acknowledged_annotated=Exists(
                    BroadcastAcknowledgement.objects.filter(broadcast_id=OuterRef("pk"), user_id=caller_id),
                ),
            )
        return qs

    @staticmethod
    def list_received(tenant_id, caller_id, caller_dept_id, caller_role_level):
        qs = BroadcastRepository._base_queryset().filter(
            tenant_id=tenant_id, status=BroadcastStatus.PUBLISHED, expires_at__gt=timezone.now(),
        )
        qs = qs.annotate(
            has_dept_restriction=Exists(
                BroadcastNoticeAudienceDept.objects.filter(broadcast_id=OuterRef("pk")),
            ),
            dept_match=Exists(
                BroadcastNoticeAudienceDept.objects.filter(
                    broadcast_id=OuterRef("pk"), department_id=caller_dept_id,
                ),
            ),
            has_role_restriction=Exists(
                BroadcastNoticeAudienceRoleLevel.objects.filter(broadcast_id=OuterRef("pk")),
            ),
            role_match=Exists(
                BroadcastNoticeAudienceRoleLevel.objects.filter(
                    broadcast_id=OuterRef("pk"), role_level=caller_role_level,
                ),
            ),
        ).filter(
            Q(has_dept_restriction=False) | Q(dept_match=True),
        ).filter(
            Q(has_role_restriction=False) | Q(role_match=True),
        )
        qs = BroadcastRepository._annotate_common(qs, caller_id=caller_id)
        return qs.order_by("-created_at")

    @staticmethod
    def list_sent(tenant_id, sender_id, from_date=None, to_date=None):
        # Excludes DRAFT (2026-08-03 upstream correction, docs/architecture/domain-model.md's
        # BroadcastNotice section) -- pending a resume/publish-draft UI action upstream.
        qs = BroadcastRepository._base_queryset().filter(
            tenant_id=tenant_id, sender_id=sender_id, status=BroadcastStatus.PUBLISHED,
        )
        # from/to narrow by createdAt (when the sender composed/sent it), not the
        # expiry window -- api-spec.md's documented semantics for these params.
        if from_date is not None:
            qs = qs.filter(created_at__gte=from_date)
        if to_date is not None:
            qs = qs.filter(created_at__lte=to_date)
        qs = BroadcastRepository._annotate_common(qs)
        return qs.order_by("-created_at")

    @staticmethod
    def attach_audience_size(tenant_id, broadcasts):
        """Live count of members currently matching each row's audience scope,
        not a publish-time snapshot -- a member who joins the tenant after
        publish still counts, matching the "still visible/ackable" rule
        already applied to the received-view audience match. Sent-view rows
        are naturally few (one sender's own broadcasts), so one extra query
        per row is fine -- same tolerance already accepted for
        TenantRepository.list_with_counts."""
        broadcast_list = list(broadcasts)
        for broadcast in broadcast_list:
            dept_ids = [d.department_id for d in broadcast.audience_depts.all()]
            role_levels = [r.role_level for r in broadcast.audience_role_levels.all()]
            broadcast.audience_size_annotated = len(
                BroadcastRepository.resolve_audience_member_user_ids(tenant_id, dept_ids, role_levels),
            )
        return broadcast_list

    @staticmethod
    def resolve_audience_member_user_ids(tenant_id, dept_ids, role_levels) -> set:
        qs = TenantMembership.objects.filter(tenant_id=tenant_id)
        if dept_ids:
            qs = qs.filter(department_id__in=dept_ids)
        if role_levels:
            qs = qs.filter(role_level__in=role_levels)
        return set(qs.values_list("user_id", flat=True))

    @staticmethod
    def create_acknowledgement(broadcast_id, user_id) -> None:
        try:
            BroadcastAcknowledgement.objects.create(broadcast_id=broadcast_id, user_id=user_id)
        except IntegrityError:
            # Composite PK (broadcastId, userId) enforces no-duplicate-ack at the DB level.
            raise ConflictError(
                "You have already acknowledged this broadcast", code="ALREADY_ACKNOWLEDGED",
            ) from None

    @staticmethod
    def ack_count(broadcast_id) -> int:
        return BroadcastAcknowledgement.objects.filter(broadcast_id=broadcast_id).count()
