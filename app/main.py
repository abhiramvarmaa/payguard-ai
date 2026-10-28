"""FastAPI application: HTTP endpoints, auth checks and request tracing."""
import logging
import time
from collections.abc import Iterator
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.investigator import LLMClient, MockLLM
from app.auth import Principal, can_access, get_principal, require_analyst
from app.cases import InvalidTransition, transition
from app.config import Settings, load_settings
from app.db import AiRunRow, AuditEventRow, CaseRow, NotificationRow, make_session_factory
from app.notifier import HttpxSender, WebhookSender, deliver_due, requeue
from app.schemas import (AiRunOut, AuditOut, CaseDetail, CaseOut, NotificationOut, PaymentFailureEvent,
                         ReviewRequest)
from app.service import IdempotencyConflict, process_event

logger = logging.getLogger("payguard")


def create_app(settings: Settings | None = None, llm: LLMClient | None = None,
               webhook_sender: WebhookSender | None = None) -> FastAPI:
    settings = settings or load_settings()
    llm = llm or MockLLM()
    webhook_sender = webhook_sender or HttpxSender()
    session_factory = make_session_factory(settings.database_url)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    app = FastAPI(title="PayGuard AI", version="0.3.0")

    @app.middleware("http")
    async def correlation_id_middleware(request: Request, call_next):
        correlation_id = request.headers.get("X-Correlation-ID") or uuid4().hex
        request.state.correlation_id = correlation_id
        started = time.perf_counter()
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = correlation_id
        logger.info("request method=%s path=%s status=%s duration_ms=%d correlation_id=%s",
                    request.method, request.url.path, response.status_code,
                    (time.perf_counter() - started) * 1000, correlation_id)
        return response

    def get_session() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    def load_case(session: Session, case_id: str, principal: Principal) -> CaseRow:
        case = session.get(CaseRow, case_id)
        # Same 404 for "missing" and "not yours", so other merchants' case IDs can't be discovered.
        if case is None or not can_access(principal, case.merchant_id):
            raise HTTPException(status_code=404, detail="Case not found")
        return case

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.post("/v1/events", status_code=201, response_model=CaseOut)
    def ingest_event(event: PaymentFailureEvent, request: Request, response: Response,
                     principal: Principal = Depends(get_principal),
                     session: Session = Depends(get_session)) -> CaseRow:
        if principal.role != "merchant" or principal.merchant_id != event.merchant_id:
            raise HTTPException(status_code=403, detail="You can only submit events for your own merchant")
        try:
            case, created = process_event(session, event, settings.ai_enabled, llm,
                                          request.state.correlation_id)
        except IdempotencyConflict:
            raise HTTPException(status_code=409, detail="event_id already used with a different payload")
        if not created:
            response.status_code = 200
        return case

    @app.get("/v1/cases", response_model=list[CaseOut])
    def list_cases(status: str | None = None,
                   principal: Principal = Depends(get_principal),
                   session: Session = Depends(get_session)) -> list[CaseRow]:
        query = select(CaseRow).order_by(CaseRow.created_at.desc())
        if principal.role != "analyst":
            query = query.where(CaseRow.merchant_id == principal.merchant_id)
        if status:
            query = query.where(CaseRow.status == status)
        return list(session.scalars(query))

    @app.get("/v1/cases/{case_id}", response_model=CaseDetail)
    def get_case(case_id: str, principal: Principal = Depends(get_principal),
                 session: Session = Depends(get_session)) -> CaseDetail:
        case = load_case(session, case_id, principal)
        audit = session.scalars(select(AuditEventRow).where(AuditEventRow.case_id == case_id)
                                .order_by(AuditEventRow.audit_id))
        runs = session.scalars(select(AiRunRow).where(AiRunRow.case_id == case_id))
        return CaseDetail(**CaseOut.model_validate(case).model_dump(),
                          audit_trail=[AuditOut.model_validate(a) for a in audit],
                          ai_runs=[AiRunOut.model_validate(r) for r in runs])

    def review(case_id: str, new_status: str, body: ReviewRequest, request: Request,
               principal: Principal, session: Session) -> CaseRow:
        case = load_case(session, case_id, principal)
        try:
            transition(session, case, new_status, principal.role,
                       request.state.correlation_id, {"reason": body.reason})
        except InvalidTransition as exc:
            raise HTTPException(status_code=409, detail=str(exc))
        session.commit()
        return case

    @app.post("/v1/cases/{case_id}/approve", response_model=CaseOut)
    def approve(case_id: str, body: ReviewRequest, request: Request,
                principal: Principal = Depends(require_analyst),
                session: Session = Depends(get_session)) -> CaseRow:
        return review(case_id, "APPROVED", body, request, principal, session)

    @app.post("/v1/cases/{case_id}/reject", response_model=CaseOut)
    def reject(case_id: str, body: ReviewRequest, request: Request,
               principal: Principal = Depends(require_analyst),
               session: Session = Depends(get_session)) -> CaseRow:
        return review(case_id, "REJECTED", body, request, principal, session)

    @app.post("/v1/cases/{case_id}/resolve", response_model=CaseOut)
    def resolve(case_id: str, body: ReviewRequest, request: Request,
                principal: Principal = Depends(require_analyst),
                session: Session = Depends(get_session)) -> CaseRow:
        return review(case_id, "RESOLVED", body, request, principal, session)

    @app.get("/v1/notifications", response_model=list[NotificationOut])
    def list_notifications(status: str | None = None,
                           principal: Principal = Depends(require_analyst),
                           session: Session = Depends(get_session)) -> list[NotificationRow]:
        query = select(NotificationRow).order_by(NotificationRow.created_at.desc())
        if status:
            query = query.where(NotificationRow.status == status)
        return list(session.scalars(query))

    @app.post("/v1/notifications/dispatch")
    def dispatch_notifications(principal: Principal = Depends(require_analyst),
                               session: Session = Depends(get_session)) -> dict[str, int]:
        # Normally app/worker.py does this on a timer; this endpoint triggers one run by hand.
        return deliver_due(session, webhook_sender)

    @app.post("/v1/notifications/{notification_id}/retry", response_model=NotificationOut)
    def retry_notification(notification_id: str,
                           principal: Principal = Depends(require_analyst),
                           session: Session = Depends(get_session)) -> NotificationRow:
        notification = session.get(NotificationRow, notification_id)
        if notification is None:
            raise HTTPException(status_code=404, detail="Notification not found")
        if notification.status != "DEAD_LETTER":
            raise HTTPException(status_code=409, detail="Only dead-lettered notifications can be retried")
        requeue(session, notification)
        return notification

    return app
