"""Orchestrator: the only place that decides, stores and triggers next steps."""
import hashlib
import logging
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.ai.investigator import LLMClient, PROMPT_VERSION, investigate
from app.cases import FINAL_STATUSES, INITIAL_STATUS, record_audit, transition
from app.db import AiRunRow, CaseRow, PaymentEventRow
from app.notifier import enqueue_case_notification
from app.router import decide
from app.schemas import PaymentFailureEvent, Route

logger = logging.getLogger("payguard")


class IdempotencyConflict(Exception):
    """Same event_id was sent again with different content."""


def payload_hash(event: PaymentFailureEvent) -> str:
    return hashlib.sha256(event.model_dump_json().encode()).hexdigest()


def _existing_case(session: Session, event: PaymentFailureEvent, digest: str) -> CaseRow | None:
    stored = session.get(PaymentEventRow, event.event_id)
    if stored is None:
        return None
    if stored.payload_hash != digest:
        raise IdempotencyConflict(event.event_id)
    return session.scalars(select(CaseRow).where(CaseRow.event_id == event.event_id)).one()


def process_event(session: Session, event: PaymentFailureEvent, ai_enabled: bool,
                  llm: LLMClient, correlation_id: str) -> tuple[CaseRow, bool]:
    """Returns (case, created). created=False means this event was already processed."""
    digest = payload_hash(event)
    existing = _existing_case(session, event, digest)
    if existing:
        return existing, False

    decision = decide(event, ai_enabled)
    case = CaseRow(
        case_id=f"case-{uuid4().hex[:12]}",
        event_id=event.event_id,
        merchant_id=event.merchant_id,
        route=decision.route.value,
        normalized_category=decision.category,
        action=decision.action,
        reason=decision.reason,
        rule_id=decision.rule_id,
        rule_version=decision.rule_version,
        status=INITIAL_STATUS[decision.route],
    )
    session.add(PaymentEventRow(
        event_id=event.event_id,
        transaction_id=event.transaction_id,
        merchant_id=event.merchant_id,
        gateway=event.gateway.value,
        raw_code=event.raw_code,
        risk_flag=event.risk_flag,
        merchant_config_valid=event.merchant_config_valid,
        payload_hash=digest,
    ))
    session.flush()  # write the event before the case that points at it
    session.add(case)
    session.flush()
    record_audit(session, case.case_id, "system", "CASE_CREATED",
                 {"route": case.route, "rule_id": case.rule_id, "rule_version": case.rule_version},
                 correlation_id)
    if case.status in FINAL_STATUSES:
        enqueue_case_notification(session, case)

    # Persist the decision BEFORE any slow or risky step, so nothing is lost if that step fails.
    try:
        session.commit()
    except IntegrityError:
        # Another request stored the same event_id a moment ago. Return its result instead.
        session.rollback()
        return _existing_case(session, event, digest), False

    logger.info("case_created case_id=%s route=%s correlation_id=%s",
                case.case_id, case.route, correlation_id)

    if decision.route == Route.AI_REVIEW:
        run_ai_review(session, case, event, llm, correlation_id)
    return case, True


def run_ai_review(session: Session, case: CaseRow, event: PaymentFailureEvent,
                  llm: LLMClient, correlation_id: str) -> None:
    run_id = f"run-{uuid4().hex[:12]}"
    try:
        result = investigate(event, case.normalized_category, llm)
    except Exception as exc:  # guardrail failure, model outage, bad output: all go to a human
        session.add(AiRunRow(run_id=run_id, case_id=case.case_id, model=llm.model_name,
                             prompt_version=PROMPT_VERSION, status="FAILED",
                             steps=[{"error": str(exc)}], input_tokens=0, output_tokens=0, latency_ms=0))
        transition(session, case, "EXCEPTION_PENDING", "system", correlation_id, {"error": str(exc)})
        session.commit()
        logger.warning("ai_review_failed case_id=%s error=%s", case.case_id, exc)
        return

    session.add(AiRunRow(run_id=run_id, case_id=case.case_id, model=llm.model_name,
                         prompt_version=PROMPT_VERSION, status="SUCCEEDED", steps=result.steps,
                         input_tokens=result.input_tokens, output_tokens=result.output_tokens,
                         latency_ms=result.latency_ms))
    case.recommendation = result.recommendation.model_dump()
    transition(session, case, "REVIEW_PENDING", "system", correlation_id, {"run_id": run_id})
    session.commit()
