"""Database tables and connection setup (SQLite locally, PostgreSQL by changing the URL)."""
from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class PaymentEventRow(Base):
    __tablename__ = "payment_events"

    event_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    transaction_id: Mapped[str] = mapped_column(String(64))
    merchant_id: Mapped[str] = mapped_column(String(64), index=True)
    gateway: Mapped[str] = mapped_column(String(32))
    raw_code: Mapped[str] = mapped_column(String(16))
    risk_flag: Mapped[bool] = mapped_column(Boolean)
    merchant_config_valid: Mapped[bool] = mapped_column(Boolean)
    payload_hash: Mapped[str] = mapped_column(String(64))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CaseRow(Base):
    __tablename__ = "cases"

    case_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("payment_events.event_id"), unique=True)
    merchant_id: Mapped[str] = mapped_column(String(64), index=True)
    route: Mapped[str] = mapped_column(String(16))
    normalized_category: Mapped[str] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(Text)
    rule_id: Mapped[str | None] = mapped_column(String(64))
    rule_version: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), index=True)
    recommendation: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditEventRow(Base):
    __tablename__ = "audit_events"

    audit_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.case_id"), index=True)
    actor: Mapped[str] = mapped_column(String(64))
    event_type: Mapped[str] = mapped_column(String(64))
    detail: Mapped[dict | None] = mapped_column(JSON)
    correlation_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AiRunRow(Base):
    __tablename__ = "ai_runs"

    run_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.case_id"), index=True)
    model: Mapped[str] = mapped_column(String(64))
    prompt_version: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16))
    steps: Mapped[list] = mapped_column(JSON)
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    latency_ms: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class NotificationRow(Base):
    """Outbox: written in the same transaction as the case change, delivered later."""

    __tablename__ = "notifications"

    notification_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("cases.case_id"), index=True)
    merchant_id: Mapped[str] = mapped_column(String(64))
    url: Mapped[str] = mapped_column(String(500))
    payload: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), index=True)  # PENDING, DELIVERED, DEAD_LETTER
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


def make_session_factory(database_url: str) -> sessionmaker:
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    engine = create_engine(database_url, connect_args=connect_args)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)
