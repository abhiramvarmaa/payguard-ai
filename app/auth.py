"""Who is calling? API key -> principal (role + merchant)."""
from dataclasses import dataclass

from fastapi import Depends, Header, HTTPException

from app.config import DEMO_API_KEYS


@dataclass(frozen=True)
class Principal:
    role: str
    merchant_id: str | None


def get_principal(x_api_key: str | None = Header(default=None)) -> Principal:
    info = DEMO_API_KEYS.get(x_api_key or "")
    if info is None:
        raise HTTPException(status_code=401, detail="Missing or invalid API key")
    return Principal(**info)


def require_analyst(principal: Principal = Depends(get_principal)) -> Principal:
    if principal.role != "analyst":
        raise HTTPException(status_code=403, detail="Analyst role required")
    return principal


def can_access(principal: Principal, merchant_id: str) -> bool:
    return principal.role == "analyst" or principal.merchant_id == merchant_id
