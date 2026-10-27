import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app

MERCHANT = {"X-API-Key": "merchant-demo-key"}
OTHER_MERCHANT = {"X-API-Key": "merchant-other-key"}
ANALYST = {"X-API-Key": "analyst-key"}


def make_event(**overrides) -> dict:
    event = {
        "event_id": "evt-1001",
        "transaction_id": "txn-2201",
        "merchant_id": "merchant-demo",
        "gateway": "simulator_visa",
        "raw_code": "V54",
        "risk_flag": False,
        "merchant_config_valid": True,
    }
    event.update(overrides)
    return event


@pytest.fixture
def client(tmp_path):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'test.db'}", ai_enabled=True)
    with TestClient(create_app(settings)) as test_client:
        yield test_client
