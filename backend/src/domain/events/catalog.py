"""The complete outbound event catalog. Adding a type requires a schema version."""

from __future__ import annotations

from typing import Final

CONTACT_CREATED: Final = "contact.created"
CONTACT_UPDATED: Final = "contact.updated"
CONTACT_DELETED: Final = "contact.deleted"
CONTACT_MERGED: Final = "contact.merged"
ACCOUNT_CREATED: Final = "account.created"
ACCOUNT_UPDATED: Final = "account.updated"
ACCOUNT_DELETED: Final = "account.deleted"
LEAD_CREATED: Final = "lead.created"
LEAD_UPDATED: Final = "lead.updated"
LEAD_CONVERTED: Final = "lead.converted"
LEAD_ASSIGNED: Final = "lead.assigned"
LEAD_QUALIFIED: Final = "lead.qualified"
LEAD_DISQUALIFIED: Final = "lead.disqualified"
OPPORTUNITY_CREATED: Final = "opportunity.created"
OPPORTUNITY_UPDATED: Final = "opportunity.updated"
OPPORTUNITY_STAGE_CHANGED: Final = "opportunity.stage_changed"
OPPORTUNITY_WON: Final = "opportunity.won"
OPPORTUNITY_LOST: Final = "opportunity.lost"
TASK_CREATED: Final = "task.created"
TASK_UPDATED: Final = "task.updated"
TASK_COMPLETED: Final = "task.completed"
APPOINTMENT_BOOKED: Final = "appointment.booked"
APPOINTMENT_CANCELLED: Final = "appointment.cancelled"
APPOINTMENT_RESCHEDULED: Final = "appointment.rescheduled"
APPOINTMENT_COMPLETED: Final = "appointment.completed"
PAYMENT_SUCCEEDED: Final = "payment.succeeded"
PAYMENT_FAILED: Final = "payment.failed"
PAYMENT_REFUNDED: Final = "payment.refunded"
CONVERSATION_CREATED: Final = "conversation.created"
CONVERSATION_MESSAGE_RECEIVED: Final = "conversation.message_received"
CONVERSATION_CLOSED: Final = "conversation.closed"
CONVERSATION_HANDOFF: Final = "conversation.handoff"
DOCUMENT_UPLOADED: Final = "document.uploaded"
DOCUMENT_CREATED: Final = "document.created"
DOCUMENT_UPDATED: Final = "document.updated"
DOCUMENT_DELETED: Final = "document.deleted"
DOCUMENT_SIGNED: Final = "document.signed"
DOCUMENT_SHARED: Final = "document.shared"
FILE_UPLOAD_REQUESTED: Final = "file.upload_requested"
FILE_UPLOAD_COMPLETED: Final = "file.upload_completed"
FILE_SCAN_COMPLETED: Final = "file.scan_completed"
FILE_DELETED: Final = "file.deleted"
ANALYTICS_EXPORT_REQUESTED: Final = "analytics.export_requested"
ANALYTICS_EVENT_EMITTED: Final = "analytics.event_emitted"
WORKFLOW_EXECUTION_STARTED: Final = "workflow.execution_started"
WORKFLOW_EXECUTION_COMPLETED: Final = "workflow.execution_completed"
WORKFLOW_EXECUTION_FAILED: Final = "workflow.execution_failed"
APPROVAL_REQUESTED: Final = "approval.requested"
APPROVAL_APPROVED: Final = "approval.approved"
APPROVAL_REJECTED: Final = "approval.rejected"
SYSTEM_QUOTA_WARNING: Final = "system.quota_warning"
SYSTEM_INTEGRATION_DISCONNECTED: Final = "system.integration_disconnected"
CONVERSATION_ASSIGNED: Final = "conversation.assigned"
CONVERSATION_RESOLVED: Final = "conversation.resolved"
MESSAGE_QUEUED: Final = "message.queued"
ACTIVITY_LOGGED: Final = "activity.logged"
NOTE_ADDED: Final = "note.added"
NOTE_UPDATED: Final = "note.updated"
CONSENT_GRANTED: Final = "consent.granted"
CONSENT_REVOKED: Final = "consent.revoked"

PUBLIC_EVENT_TYPES: Final[frozenset[str]] = frozenset(
    {
        CONVERSATION_ASSIGNED,
        CONVERSATION_RESOLVED,
        MESSAGE_QUEUED,
        ACTIVITY_LOGGED,
        NOTE_ADDED,
        NOTE_UPDATED,
        CONTACT_CREATED,
        CONTACT_UPDATED,
        CONTACT_DELETED,
        CONTACT_MERGED,
        ACCOUNT_CREATED,
        ACCOUNT_UPDATED,
        ACCOUNT_DELETED,
        LEAD_CREATED,
        LEAD_UPDATED,
        LEAD_CONVERTED,
        LEAD_ASSIGNED,
        OPPORTUNITY_CREATED,
        OPPORTUNITY_UPDATED,
        OPPORTUNITY_STAGE_CHANGED,
        OPPORTUNITY_WON,
        OPPORTUNITY_LOST,
        TASK_CREATED,
        TASK_UPDATED,
        TASK_COMPLETED,
        APPOINTMENT_BOOKED,
        APPOINTMENT_CANCELLED,
        APPOINTMENT_RESCHEDULED,
        APPOINTMENT_COMPLETED,
        PAYMENT_SUCCEEDED,
        PAYMENT_FAILED,
        PAYMENT_REFUNDED,
        CONVERSATION_CREATED,
        CONVERSATION_MESSAGE_RECEIVED,
        CONVERSATION_CLOSED,
        DOCUMENT_UPLOADED,
        DOCUMENT_CREATED,
        DOCUMENT_UPDATED,
        DOCUMENT_DELETED,
        DOCUMENT_SIGNED,
        DOCUMENT_SHARED,
        WORKFLOW_EXECUTION_STARTED,
        WORKFLOW_EXECUTION_COMPLETED,
        WORKFLOW_EXECUTION_FAILED,
        APPROVAL_REQUESTED,
        APPROVAL_APPROVED,
        APPROVAL_REJECTED,
        SYSTEM_QUOTA_WARNING,
        SYSTEM_INTEGRATION_DISCONNECTED,
    }
)

# Internal-only events never leave the platform via outbound webhooks.
INTERNAL_EVENT_TYPES: Final[frozenset[str]] = frozenset(
    {
        LEAD_QUALIFIED,
        LEAD_DISQUALIFIED,
        CONVERSATION_HANDOFF,
        CONSENT_GRANTED,
        CONSENT_REVOKED,
        FILE_UPLOAD_REQUESTED,
        FILE_UPLOAD_COMPLETED,
        FILE_SCAN_COMPLETED,
        FILE_DELETED,
        ANALYTICS_EXPORT_REQUESTED,
        ANALYTICS_EVENT_EMITTED,
    }
)

ALL_EVENT_TYPES: Final[frozenset[str]] = PUBLIC_EVENT_TYPES | INTERNAL_EVENT_TYPES


def is_public(event_type: str) -> bool:
    return event_type in PUBLIC_EVENT_TYPES
