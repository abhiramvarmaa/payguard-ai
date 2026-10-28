"""Merchant webhooks with the outbox pattern, exponential backoff and a dead-letter queue.

Delivery is at-least-once: a merchant may receive the same message twice, so every
message carries an Idempotency-Key the merchant uses to ignore repeats.
"""
from datetime import datetime, timedelta
from typing import Protocol
from uuid import uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import MERCHANT_WEBHOOKS
from app.db import CaseRow, NotificationRow, utcnow

MAX_ATTEMPTS = 5
BASE_DELAY_SECONDS = 30


class WebhookSender(Protocol):
    def send(self, url: str, payload: dict, headers: dict) -> int: ...


class HttpxSender:
    def __init__(self, timeout_seconds: float = 5.0):
        self.timeout_seconds = timeout_seconds

    def send(self, url: str, payload: dict, headers: dict) -> int:
        return httpx.post(url, json=payload, headers=headers, timeout=self.timeout_seconds).status_code


def enqueue_case_notification(session: Session, case: CaseRow) -> None:
    url = MERCHANT_WEBHOOKS.get(case.merchant_id)
    if url is None:
        return
    # Only what the merchant needs: no risk signals, model output or internal notes.
    payload = {
        "type": "case.updated",
        "case_id": case.case_id,
        "event_id": case.event_id,
        "status": case.status,
        "action": case.action,
        "reason": case.reason,
    }
    session.add(NotificationRow(notification_id=f"ntf-{uuid4().hex[:12]}", case_id=case.case_id,
                                merchant_id=case.merchant_id, url=url, payload=payload,
                                status="PENDING", attempts=0, next_attempt_at=utcnow()))


def backoff_delay(attempts: int) -> timedelta:
    """30s, 60s, 120s, 240s... after the 1st, 2nd, 3rd, 4th failure."""
    return timedelta(seconds=BASE_DELAY_SECONDS * 2 ** (attempts - 1))


def deliver_due(session: Session, sender: WebhookSender, now: datetime | None = None) -> dict[str, int]:
    now = now or utcnow()
    due = session.scalars(
        select(NotificationRow)
        .where(NotificationRow.status == "PENDING", NotificationRow.next_attempt_at <= now)
        .order_by(NotificationRow.created_at)
    ).all()

    counts = {"delivered": 0, "retrying": 0, "dead_letter": 0}
    for notification in due:
        notification.attempts += 1
        try:
            status_code = sender.send(notification.url, notification.payload,
                                      {"Idempotency-Key": notification.notification_id})
            error = None if 200 <= status_code < 300 else f"HTTP {status_code}"
            # 4xx means the request itself is wrong; retrying won't help. 429 means "slow down", so retry.
            permanent = 400 <= status_code < 500 and status_code != 429
        except Exception as exc:  # timeouts, refused connections, DNS errors: all worth retrying
            error = f"{type(exc).__name__}: {exc}"
            permanent = False

        if error is None:
            notification.status = "DELIVERED"
            notification.last_error = None
            counts["delivered"] += 1
        elif permanent or notification.attempts >= MAX_ATTEMPTS:
            notification.status = "DEAD_LETTER"
            notification.last_error = error
            counts["dead_letter"] += 1
        else:
            notification.next_attempt_at = now + backoff_delay(notification.attempts)
            notification.last_error = error
            counts["retrying"] += 1
        # Commit each one, so a crash halfway through doesn't resend those already delivered.
        session.commit()
    return counts


def requeue(session: Session, notification: NotificationRow) -> None:
    """Operator action: give a dead-lettered message a fresh set of attempts."""
    notification.status = "PENDING"
    notification.attempts = 0
    notification.next_attempt_at = utcnow()
    session.commit()
