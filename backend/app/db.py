"""SQLite-хранилище. Общий volume /data используют api и worker; WAL допускает их одновременную работу."""
import json
import sqlite3
import uuid
from contextlib import closing
from datetime import date, datetime

from .config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS meetings (
    id           TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    meeting_date TEXT NOT NULL,
    filename     TEXT NOT NULL,
    participants TEXT,                              -- "Имя — должность" построчно, подсказка для ASR и LLM
    consent      INTEGER NOT NULL DEFAULT 0,
    num_speakers INTEGER NOT NULL DEFAULT 0,
    status       TEXT NOT NULL DEFAULT 'queued',   -- queued | processing | done | error
    stage        TEXT,
    error        TEXT,
    language     TEXT,
    duration     REAL,
    summary      TEXT,
    llm_used     INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL,
    finished_at  TEXT
);
CREATE TABLE IF NOT EXISTS segments (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    start      REAL NOT NULL,
    end        REAL NOT NULL,
    speaker    TEXT NOT NULL,
    text       TEXT NOT NULL,
    lang       TEXT               -- ru | kk | mixed | ''
);
CREATE TABLE IF NOT EXISTS speakers (
    meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    label      TEXT NOT NULL,
    name       TEXT,
    role       TEXT,
    PRIMARY KEY (meeting_id, label)
);
CREATE TABLE IF NOT EXISTS tasks (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id       TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    description      TEXT NOT NULL,
    assignee         TEXT,
    assignee_speaker TEXT,          -- метка диаризации ответственного, если он участник
    issuer_speaker   TEXT,          -- кто дал поручение
    deadline_text    TEXT,          -- срок дословно
    due_date         TEXT,          -- нормализованная дата (ISO) или NULL
    priority         TEXT,
    category         TEXT,
    quote            TEXT,
    status           TEXT NOT NULL DEFAULT 'in_progress',  -- in_progress | done
    created_at       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS app_settings (
    section    TEXT PRIMARY KEY,   -- раздел из config.SECTIONS
    value      TEXT NOT NULL,      -- JSON: поле -> значение (без секретов)
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_segments_meeting ON segments(meeting_id);
CREATE INDEX IF NOT EXISTS idx_tasks_meeting ON tasks(meeting_id);
"""


def connect() -> sqlite3.Connection:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(settings.db_path, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# Колонки, добавленные после первой версии схемы: база, созданная раньше, дополняется при старте.
MIGRATIONS = [("meetings", "participants", "TEXT"), ("segments", "lang", "TEXT")]


def init() -> None:
    with closing(connect()) as c:
        c.executescript(SCHEMA)
        for table, column, kind in MIGRATIONS:
            if column not in {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {kind}")


def now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def rows(sql: str, *args) -> list[dict]:
    with closing(connect()) as c:
        return [dict(r) for r in c.execute(sql, args).fetchall()]


def row(sql: str, *args) -> dict | None:
    found = rows(sql, *args)
    return found[0] if found else None


def execute(sql: str, *args) -> int:
    with closing(connect()) as c:
        return c.execute(sql, args).lastrowid


# --- настройки из интерфейса ---------------------------------------------------

def save_settings(section: str, values: dict) -> None:
    execute("INSERT INTO app_settings (section, value, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT (section) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            section, json.dumps(values, ensure_ascii=False), now())


def settings_updated_at() -> dict[str, str]:
    return {r["section"]: r["updated_at"] for r in rows("SELECT section, updated_at FROM app_settings")}


# --- meetings ---------------------------------------------------------------

def create_meeting(title: str, meeting_date: str, filename: str, consent: bool, num_speakers: int,
                   participants: str = "") -> str:
    meeting_id = uuid.uuid4().hex[:12]
    execute(
        "INSERT INTO meetings (id, title, meeting_date, filename, consent, num_speakers, participants, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        meeting_id, title, meeting_date, filename, int(consent), num_speakers, participants, now(),
    )
    return meeting_id


def claim_next_meeting() -> dict | None:
    """Атомарно забирает следующую запись из очереди."""
    with closing(connect()) as c:
        c.execute("BEGIN IMMEDIATE")
        found = c.execute(
            "SELECT * FROM meetings WHERE status = 'queued' ORDER BY created_at LIMIT 1"
        ).fetchone()
        if found:
            c.execute("UPDATE meetings SET status = 'processing', stage = 'start', error = NULL WHERE id = ?",
                      (found["id"],))
        c.execute("COMMIT")
        return dict(found) if found else None


def set_stage(meeting_id: str, stage: str) -> None:
    execute("UPDATE meetings SET stage = ? WHERE id = ?", stage, meeting_id)


def fail_meeting(meeting_id: str, error: str) -> None:
    execute("UPDATE meetings SET status = 'error', error = ?, finished_at = ? WHERE id = ?",
            error[:2000], now(), meeting_id)


def save_result(meeting_id: str, *, language, duration, segments, speakers, tasks, summary, llm_used) -> None:
    with closing(connect()) as c:
        c.execute("BEGIN")
        for table in ("segments", "speakers", "tasks"):
            c.execute(f"DELETE FROM {table} WHERE meeting_id = ?", (meeting_id,))
        c.executemany(
            "INSERT INTO segments (meeting_id, start, end, speaker, text, lang) VALUES (?, ?, ?, ?, ?, ?)",
            [(meeting_id, s["start"], s["end"], s["speaker"], s["text"], s.get("lang")) for s in segments],
        )
        c.executemany(
            "INSERT INTO speakers (meeting_id, label, name, role) VALUES (?, ?, ?, ?)",
            [(meeting_id, s["label"], s.get("name"), s.get("role")) for s in speakers],
        )
        created = now()
        c.executemany(
            "INSERT INTO tasks (meeting_id, description, assignee, assignee_speaker, issuer_speaker,"
            " deadline_text, due_date, priority, category, quote, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(meeting_id, t["description"], t.get("assignee"), t.get("assignee_speaker"),
              t.get("issuer_speaker"), t.get("deadline_text"), t.get("due_date"), t.get("priority"),
              t.get("category"), t.get("quote"), created) for t in tasks],
        )
        c.execute(
            "UPDATE meetings SET status = 'done', stage = 'done', language = ?, duration = ?, summary = ?,"
            " llm_used = ?, finished_at = ? WHERE id = ?",
            (language, duration, summary, int(llm_used), created, meeting_id),
        )
        c.execute("COMMIT")


def meeting_bundle(meeting_id: str) -> dict | None:
    meeting = row("SELECT * FROM meetings WHERE id = ?", meeting_id)
    if not meeting:
        return None
    meeting["speakers"] = rows("SELECT label, name, role FROM speakers WHERE meeting_id = ? ORDER BY label",
                               meeting_id)
    meeting["segments"] = rows("SELECT start, end, speaker, text, lang FROM segments WHERE meeting_id = ? ORDER BY start",
                               meeting_id)
    meeting["tasks"] = list_tasks(meeting_id=meeting_id)
    return meeting


# --- tasks -------------------------------------------------------------------

def task_state(task: dict, today: date | None = None) -> str:
    """Статус для дашборда: done | overdue | in_progress."""
    if task["status"] == "done":
        return "done"
    today = today or date.today()
    if task.get("due_date") and date.fromisoformat(task["due_date"]) < today:
        return "overdue"
    return "in_progress"


def list_tasks(meeting_id: str | None = None) -> list[dict]:
    sql = ("SELECT t.*, m.title AS meeting_title, m.meeting_date,"
           " s.name AS assignee_speaker_name"
           " FROM tasks t JOIN meetings m ON m.id = t.meeting_id"
           " LEFT JOIN speakers s ON s.meeting_id = t.meeting_id AND s.label = t.assignee_speaker")
    args: tuple = ()
    if meeting_id:
        sql += " WHERE t.meeting_id = ?"
        args = (meeting_id,)
    sql += " ORDER BY t.due_date IS NULL, t.due_date, t.id"
    found = rows(sql, *args)
    for task in found:
        task["state"] = task_state(task)
    return found
