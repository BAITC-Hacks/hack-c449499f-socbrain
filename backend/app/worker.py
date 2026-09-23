"""Фоновый обработчик: берёт записи из очереди (таблица meetings) и прогоняет конвейер."""
import logging
import time

from . import db
from .pipeline import runner

POLL_SECONDS = 3

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("worker")


def main() -> None:
    db.init()
    # записи, прерванные падением/перезапуском, возвращаем в очередь
    db.execute("UPDATE meetings SET status = 'queued' WHERE status = 'processing'")
    log.info("worker started")
    while True:
        meeting = db.claim_next_meeting()
        if meeting:
            log.info("processing meeting %s (%s)", meeting["id"], meeting["title"])
            runner.process(meeting)
        else:
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
