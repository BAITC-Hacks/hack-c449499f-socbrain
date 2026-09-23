"""Фоновый обработчик: берёт записи из очереди (таблица meetings) и прогоняет конвейер."""
import logging
import time
from datetime import datetime, timedelta

from . import db
from .config import settings
from .pipeline import runner

POLL_SECONDS = 3
PURGE_EVERY_SECONDS = 3600

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("worker")


def purge_old_audio() -> None:
    """Удалить исходные записи старше срока хранения (Настройки → Обработка). Протокол и стенограмма остаются."""
    days = settings.audio_retention_days
    if days <= 0:  # 0 = хранить бессрочно
        return
    cutoff = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    for m in db.rows("SELECT id, filename FROM meetings WHERE status = 'done' AND finished_at < ? AND filename != ''",
                     cutoff):
        (settings.upload_dir / m["filename"]).unlink(missing_ok=True)
        db.execute("UPDATE meetings SET filename = '' WHERE id = ?", m["id"])
        log.info("audio of meeting %s deleted after %d days", m["id"], days)


def main() -> None:
    db.init()
    # записи, прерванные падением/перезапуском, возвращаем в очередь
    db.execute("UPDATE meetings SET status = 'queued' WHERE status = 'processing'")
    log.info("worker started")
    last_purge = 0.0
    while True:
        # Настройки из интерфейса применяются к следующей записи без перезапуска контейнера.
        settings.reload()
        if time.monotonic() - last_purge > PURGE_EVERY_SECONDS:
            purge_old_audio()
            last_purge = time.monotonic()
        meeting = db.claim_next_meeting()
        if meeting:
            log.info("processing meeting %s (%s)", meeting["id"], meeting["title"])
            runner.process(meeting)
        else:
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
