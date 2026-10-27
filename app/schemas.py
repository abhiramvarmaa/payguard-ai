"""API contracts: what clients send in and what they get back."""
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

ID_PATTERN = r"^[A-Za-z0-9_-]{1,64}$"


class Gateway(str, Enum):
    SIMULATOR_VISA = "simulator_visa"
    SIMULATOR_MASTERCARD = "simulator_mastercard"


class Route(str, Enum):
    DETERMINISTIC = "DETERMINISTIC"
    AI_REVIEW = "AI_REVIEW"
    EXCEPTION = "EXCEPTION"


class PaymentFailureEvent(BaseModel):
    # Unknown fields are rejected, so nobody can slip a card number into the payload.
    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(pattern=ID_PATTERN)
    transaction_id: str = Field(pattern=ID_PATTERN)
    merchant_id: str = Field(pattern=ID_PATTERN)
    gateway: Gateway
    raw_code: str = Field(min_length=1, max_length=16)
    risk_flag: bool = False
    merchant_config_valid: bool = True


class ReviewRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


class CaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    case_id: str
    event_id: str
    merchant_id: str
    route: Route
    normalized_category: str
    action: str
    reason: str
    rule_id: str | None
    rule_version: int | None
    status: str
    recommendation: dict | None
    created_at: datetime
    updated_at: datetime


class AuditOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    actor: str
    event_type: str
    detail: dict | None
    correlation_id: str
    created_at: datetime


class AiRunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    run_id: str
    model: str
    prompt_version: str
    status: str
    steps: list
    input_tokens: int
    output_tokens: int
    latency_ms: int


class CaseDetail(CaseOut):
    audit_trail: list[AuditOut]
    ai_runs: list[AiRunOut]
