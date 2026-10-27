"""Application settings, read from environment variables."""
import os
from dataclasses import dataclass

# Demo API keys. A real deployment would load these from a secrets manager.
DEMO_API_KEYS = {
    "merchant-demo-key": {"role": "merchant", "merchant_id": "merchant-demo"},
    "merchant-other-key": {"role": "merchant", "merchant_id": "merchant-other"},
    "analyst-key": {"role": "analyst", "merchant_id": None},
}


@dataclass(frozen=True)
class Settings:
    database_url: str
    ai_enabled: bool


def load_settings() -> Settings:
    return Settings(
        database_url=os.getenv("PAYGUARD_DATABASE_URL", "sqlite:///./payguard.db"),
        ai_enabled=os.getenv("PAYGUARD_AI_ENABLED", "true").lower() == "true",
    )
