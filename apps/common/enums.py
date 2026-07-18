from django.db import models


class Vertical(models.TextChoices):
    EDUCATION = "EDUCATION", "Education"
    CA_CS = "CA_CS", "CA/CS"


class OrgRoleLevel(models.TextChoices):
    TOP = "TOP", "Top"
    MID = "MID", "Mid"
    EXECUTOR = "EXECUTOR", "Executor"


class Language(models.TextChoices):
    EN = "EN", "English"
    HI = "HI", "Hindi"


class TaskStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    OPEN = "OPEN", "Open"
    IN_PROGRESS = "IN_PROGRESS", "In Progress"
    OVERDUE = "OVERDUE", "Overdue"
    DONE_A = "DONE_A", "Done (Assignee)"
    DONE_D = "DONE_D", "Done (Delegator)"
    CANCELLED = "CANCELLED", "Cancelled"


class AcceptanceStatus(models.TextChoices):
    PENDING = "PENDING", "Pending"
    ACCEPTED = "ACCEPTED", "Accepted"


class Priority(models.TextChoices):
    P1 = "P1", "P1"
    P2 = "P2", "P2"
    P3 = "P3", "P3"
    P4 = "P4", "P4"


class EvidenceType(models.TextChoices):
    IMAGE = "IMAGE", "Image"
    PDF = "PDF", "PDF"
    DOC = "DOC", "Document"
    OTHER = "OTHER", "Other"


class BroadcastStatus(models.TextChoices):
    DRAFT = "DRAFT", "Draft"
    PUBLISHED = "PUBLISHED", "Published"


class AuditActorType(models.TextChoices):
    USER = "USER", "User"
    SYSTEM = "SYSTEM", "System"
    # PlatformAdmin is a separate model, not a User row -- actor_id stays null for these
    PLATFORM_ADMIN = "PLATFORM_ADMIN", "Platform Admin"


class AuditAction(models.TextChoices):
    # Task & Subtask
    TASK_CREATED = "TASK_CREATED", "Task Created"
    TASK_UPDATED = "TASK_UPDATED", "Task Updated"
    TASK_DELETED = "TASK_DELETED", "Task Deleted"
    TASK_ASSIGNED = "TASK_ASSIGNED", "Task Assigned"
    TASK_REASSIGNED = "TASK_REASSIGNED", "Task Reassigned"
    TASK_STATUS_CHANGED = "TASK_STATUS_CHANGED", "Task Status Changed"
    TASK_PRIORITY_CHANGED = "TASK_PRIORITY_CHANGED", "Task Priority Changed"
    TASK_DUE_DATE_CHANGED = "TASK_DUE_DATE_CHANGED", "Task Due Date Changed"
    TASK_LABEL_CHANGED = "TASK_LABEL_CHANGED", "Task Label Changed"
    TASK_ARCHIVED = "TASK_ARCHIVED", "Task Archived"
    SUBTASK_CREATED = "SUBTASK_CREATED", "Subtask Created"
    SUBTASK_UPDATED = "SUBTASK_UPDATED", "Subtask Updated"
    SUBTASK_DELETED = "SUBTASK_DELETED", "Subtask Deleted"
    # Documents
    DOCUMENT_UPLOADED = "DOCUMENT_UPLOADED", "Document Uploaded"
    DOCUMENT_DELETED = "DOCUMENT_DELETED", "Document Deleted"
    DOCUMENT_DOWNLOADED = "DOCUMENT_DOWNLOADED", "Document Downloaded"
    DOCUMENT_ACCESSED = "DOCUMENT_ACCESSED", "Document Accessed"
    # Broadcast
    BROADCAST_CREATED = "BROADCAST_CREATED", "Broadcast Created"
    BROADCAST_UPDATED = "BROADCAST_UPDATED", "Broadcast Updated"
    BROADCAST_DELETED = "BROADCAST_DELETED", "Broadcast Deleted"
    BROADCAST_PUBLISHED = "BROADCAST_PUBLISHED", "Broadcast Published"
    BROADCAST_ACKNOWLEDGED = "BROADCAST_ACKNOWLEDGED", "Broadcast Acknowledged"
    BROADCAST_VIEWED = "BROADCAST_VIEWED", "Broadcast Viewed"
    # Audience Scope
    AUDIENCE_SCOPE_CREATED = "AUDIENCE_SCOPE_CREATED", "Audience Scope Created"
    AUDIENCE_SCOPE_MODIFIED = "AUDIENCE_SCOPE_MODIFIED", "Audience Scope Modified"
    AUDIENCE_SCOPE_ASSIGNMENT_CHANGED = (
        "AUDIENCE_SCOPE_ASSIGNMENT_CHANGED",
        "Audience Scope Assignment Changed",
    )
    # User Activity
    USER_LOGIN = "USER_LOGIN", "User Login"
    USER_LOGOUT = "USER_LOGOUT", "User Logout"
    USER_PROFILE_UPDATED = "USER_PROFILE_UPDATED", "User Profile Updated"
    USER_ROLE_CHANGED = "USER_ROLE_CHANGED", "User Role Changed"
    USER_PERMISSION_CHANGED = "USER_PERMISSION_CHANGED", "User Permission Changed"
    # Platform Admin (cross-tenant/superadmin)
    TENANT_CREATED = "TENANT_CREATED", "Tenant Created"
    MEMBER_ADDED = "MEMBER_ADDED", "Member Added"
    MEMBER_REMOVED = "MEMBER_REMOVED", "Member Removed"
    MEMBERS_BULK_IMPORTED = "MEMBERS_BULK_IMPORTED", "Members Bulk Imported"


class NotificationType(models.TextChoices):
    # Task
    TASK_ASSIGNED = "TASK_ASSIGNED", "Task Assigned"
    TASK_ACCEPTED = "TASK_ACCEPTED", "Task Accepted"
    TASK_REASSIGNED = "TASK_REASSIGNED", "Task Reassigned"
    TASK_EDITED = "TASK_EDITED", "Task Edited"
    TASK_COMMENTED = "TASK_COMMENTED", "Task Commented"
    TASK_DONE_A = "TASK_DONE_A", "Task Done (Assignee)"
    TASK_DONE_D = "TASK_DONE_D", "Task Done (Delegator)"
    TASK_CANCELLED = "TASK_CANCELLED", "Task Cancelled"
    TASK_REMINDER = "TASK_REMINDER", "Task Reminder"
    TASK_DUE_TODAY = "TASK_DUE_TODAY", "Task Due Today"
    TASK_DUE_TOMORROW = "TASK_DUE_TOMORROW", "Task Due Tomorrow"
    TASK_OVERDUE = "TASK_OVERDUE", "Task Overdue"
    # Subtask
    SUBTASK_CREATED = "SUBTASK_CREATED", "Subtask Created"
    SUBTASK_EDITED = "SUBTASK_EDITED", "Subtask Edited"
    SUBTASK_DONE_A = "SUBTASK_DONE_A", "Subtask Done (Assignee)"
    SUBTASK_DONE_D = "SUBTASK_DONE_D", "Subtask Done (Delegator)"
    # Broadcast
    BROADCAST_POSTED = "BROADCAST_POSTED", "Broadcast Posted"
    # Evidence
    EVIDENCE_ATTACHED = "EVIDENCE_ATTACHED", "Evidence Attached"
    # Reminder (StickyNote with dueAt)
    REMINDER_FIRED = "REMINDER_FIRED", "Reminder Fired"
    # AI Nudge -- only 2 types remain (AI_NUDGE_PERIODIC retired 2026-07-06)
    AI_NUDGE_FOLLOWUP = "AI_NUDGE_FOLLOWUP", "AI Nudge - Follow-up"
    AI_NUDGE_DUE_PROXIMITY = "AI_NUDGE_DUE_PROXIMITY", "AI Nudge - Due Proximity"
