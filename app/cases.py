"""Case state machine and audit trail."""
from sqlalchemy.orm import Session

from app.db import AuditEventRow, CaseRow, utcnow
from app.schemas import Route

INITIAL_STATUS = {
    Route.DETERMINISTIC: "RULE_COMPLETE",
    Route.AI_REVIEW: "AI_PENDING",
    Route.EXCEPTION: "EXCEPTION_PENDING",
}

# Every status change must be listed here. Anything else is refused.
ALLOWED_TRANSITIONS: dict[str, set[str]] = {
    "AI_PENDING": {"REVIEW_PENDING", "EXCEPTION_PENDING"},
    "REVIEW_PENDING": {"APPROVED", "REJECTED"},
    "EXCEPTION_PENDING": {"RESOLVED"},
}


class InvalidTransition(Exception):
    pass


def record_audit(session: Session, case_id: str, actor: str, event_type: str,
                 detail: dict | None, correlation_id: str) -> None:
    session.add(AuditEventRow(case_id=case_id, actor=actor, event_type=event_type,
                              detail=detail, correlation_id=correlation_id))


def transition(session: Session, case: CaseRow, new_status: str, actor: str,
               correlation_id: str, detail: dict | None = None) -> None:
    if new_status not in ALLOWED_TRANSITIONS.get(case.status, set()):
        raise InvalidTransition(f"Cannot move case from {case.status} to {new_status}")
    old_status = case.status
    case.status = new_status
    case.updated_at = utcnow()
    record_audit(session, case.case_id, actor, f"STATUS_{old_status}_TO_{new_status}",
                 detail, correlation_id)
