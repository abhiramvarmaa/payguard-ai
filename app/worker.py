"""Background worker: delivers due webhooks every few seconds.

Run:  python -m app.worker
"""
import logging
import time

from app.config import load_settings
from app.db import make_session_factory
from app.notifier import HttpxSender, deliver_due

POLL_SECONDS = 5
logger = logging.getLogger("payguard.worker")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    session_factory = make_session_factory(load_settings().database_url)
    sender = HttpxSender()
    logger.info("worker started, polling every %ss", POLL_SECONDS)
    while True:
        with session_factory() as session:
            counts = deliver_due(session, sender)
        if any(counts.values()):
            logger.info("delivery run %s", counts)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
