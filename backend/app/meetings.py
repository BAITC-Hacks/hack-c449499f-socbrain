"""Совещания и извлечённые из них поручения — минимальное хранение,
без диаризации (она следующим шагом поверх текста)."""

from .db import get_conn


def create_meeting(title: str, language: str, transcript: str) -> int:
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO meetings (title, language, transcript) VALUES (?, ?, ?)",
            (title, language, transcript),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def get_meeting(meeting_id: int) -> dict | None:
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM meetings WHERE id = ?", (meeting_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def list_meetings() -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT id, title, language, created_at, "
            "(SELECT COUNT(*) FROM tasks WHERE tasks.meeting_id = meetings.id) AS task_count "
            "FROM meetings ORDER BY id DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def save_tasks(meeting_id: int, tasks: list[dict]) -> list[dict]:
    """tasks: [{"assignee", "task", "deadline"}] — как отдаёт tasks_extraction."""
    conn = get_conn()
    try:
        saved = []
        for t in tasks:
            cur = conn.execute(
                "INSERT INTO tasks (meeting_id, assignee, description, deadline) VALUES (?, ?, ?, ?)",
                (meeting_id, t.get("assignee", "").strip(), t.get("task", "").strip(), t.get("deadline")),
            )
            saved.append({"id": cur.lastrowid, **t})
        conn.commit()
        return saved
    finally:
        conn.close()


def list_tasks(meeting_id: int | None = None) -> list[dict]:
    conn = get_conn()
    try:
        if meeting_id is not None:
            rows = conn.execute(
                "SELECT tasks.*, meetings.title AS meeting_title FROM tasks "
                "JOIN meetings ON meetings.id = tasks.meeting_id "
                "WHERE meeting_id = ? ORDER BY tasks.id",
                (meeting_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT tasks.*, meetings.title AS meeting_title FROM tasks "
                "JOIN meetings ON meetings.id = tasks.meeting_id "
                "ORDER BY tasks.id DESC"
            ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
