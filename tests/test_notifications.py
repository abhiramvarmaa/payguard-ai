"""Webhook tests: outbox, retries with backoff, dead-letter queue and requeue."""
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.ai.investigator import MockLLM
from app.config import Settings
from app.db import NotificationRow, make_session_factory, utcnow
from app.main import create_app
from app.notifier import MAX_ATTEMPTS, backoff_delay, deliver_due
from app.schemas import PaymentFailureEvent
from app.service import process_event
from tests.conftest import ANALYST, MERCHANT, OTHER_MERCHANT, make_event


class FakeSender:
    """Records every webhook and answers with scripted results (status codes or exceptions)."""

    def __init__(self, *results):
        self.results = list(results)
        self.calls = []

    def send(self, url, payload, headers):
        self.calls.append({"url": url, "payload": payload, "headers": headers})
        result = self.results.pop(0) if self.results else 200
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture
def sender():
    return FakeSender()


@pytest.fixture
def api(tmp_path, sender):
    settings = Settings(database_url=f"sqlite:///{tmp_path / 'test.db'}", ai_enabled=True)
    with TestClient(create_app(settings, webhook_sender=sender)) as test_client:
        yield test_client


@pytest.fixture
def session(tmp_path):
    with make_session_factory(f"sqlite:///{tmp_path / 'unit.db'}")() as db_session:
        yield db_session


def queue_one(session):
    """Creates a rule-path case, which queues exactly one notification."""
    process_event(session, PaymentFailureEvent(**make_event()), True, MockLLM(), "test")
    return session.query(NotificationRow).one()


def test_rule_case_is_queued_then_delivered_with_idempotency_key(api, sender):
    case = api.post("/v1/events", json=make_event(), headers=MERCHANT).json()
    [queued] = api.get("/v1/notifications", headers=ANALYST).json()
    assert (queued["status"], queued["case_id"]) == ("PENDING", case["case_id"])

    assert api.post("/v1/notifications/dispatch", headers=ANALYST).json() == {
        "delivered": 1, "retrying": 0, "dead_letter": 0}
    [call] = sender.calls
    assert call["headers"]["Idempotency-Key"] == queued["notification_id"]
    assert call["payload"]["status"] == "RULE_COMPLETE"
    # Internal details never leave the bank.
    assert "recommendation" not in call["payload"] and "risk_flag" not in call["payload"]

    # Delivered messages are not sent again.
    api.post("/v1/notifications/dispatch", headers=ANALYST)
    assert len(sender.calls) == 1


def test_ai_case_notifies_only_after_human_decision(api):
    event = make_event(event_id="evt-3001", transaction_id="txn-3001", raw_code="V91")
    case = api.post("/v1/events", json=event, headers=MERCHANT).json()
    assert api.get("/v1/notifications", headers=ANALYST).json() == []

    api.post(f"/v1/cases/{case['case_id']}/approve", json={"reason": "Verified"}, headers=ANALYST)
    [queued] = api.get("/v1/notifications", headers=ANALYST).json()
    assert queued["payload"]["status"] == "APPROVED"


def test_merchant_without_webhook_url_gets_nothing(api):
    api.post("/v1/events", json=make_event(merchant_id="merchant-other"), headers=OTHER_MERCHANT)
    assert api.get("/v1/notifications", headers=ANALYST).json() == []


def test_only_analysts_can_see_or_dispatch(api):
    assert api.get("/v1/notifications", headers=MERCHANT).status_code == 403
    assert api.post("/v1/notifications/dispatch", headers=MERCHANT).status_code == 403


def test_backoff_doubles():
    assert [backoff_delay(n).total_seconds() for n in (1, 2, 3, 4)] == [30, 60, 120, 240]


def test_failure_waits_for_backoff_before_retrying(session):
    notification = queue_one(session)
    now = utcnow()
    sender = FakeSender(503, 200)

    assert deliver_due(session, sender, now)["retrying"] == 1
    assert (notification.attempts, notification.last_error) == (1, "HTTP 503")

    # Too early: the 30-second backoff hasn't passed.
    assert deliver_due(session, sender, now + timedelta(seconds=29)) == {
        "delivered": 0, "retrying": 0, "dead_letter": 0}
    assert deliver_due(session, sender, now + timedelta(seconds=31))["delivered"] == 1
    assert notification.status == "DELIVERED"


def test_network_errors_are_retried(session):
    notification = queue_one(session)
    deliver_due(session, FakeSender(ConnectionError("refused")))
    assert notification.status == "PENDING"
    assert notification.last_error.startswith("ConnectionError")


def test_gives_up_after_max_attempts(session):
    notification = queue_one(session)
    sender = FakeSender(*[500] * MAX_ATTEMPTS)
    now = utcnow()
    for _ in range(MAX_ATTEMPTS):
        deliver_due(session, sender, now)
        now += timedelta(hours=1)
    assert (notification.status, notification.attempts) == ("DEAD_LETTER", MAX_ATTEMPTS)


@pytest.mark.parametrize("code, expected", [(400, "DEAD_LETTER"), (404, "DEAD_LETTER"), (429, "PENDING")])
def test_client_errors_are_permanent_except_429(session, code, expected):
    notification = queue_one(session)
    deliver_due(session, FakeSender(code))
    assert notification.status == expected


def test_operator_can_requeue_a_dead_letter(api, sender):
    sender.results = [400]  # merchant endpoint rejects the first try
    api.post("/v1/events", json=make_event(), headers=MERCHANT)
    [queued] = api.get("/v1/notifications", headers=ANALYST).json()
    url = f"/v1/notifications/{queued['notification_id']}/retry"
    assert api.post(url, headers=ANALYST).status_code == 409  # still PENDING: nothing to retry yet

    api.post("/v1/notifications/dispatch", headers=ANALYST)
    [dead] = api.get("/v1/notifications?status=DEAD_LETTER", headers=ANALYST).json()
    assert dead["last_error"] == "HTTP 400"

    # The merchant fixes their endpoint; the operator requeues and it goes through.
    assert api.post(url, headers=ANALYST).json()["status"] == "PENDING"
    assert api.post("/v1/notifications/dispatch", headers=ANALYST).json()["delivered"] == 1
