"""Журнал доступа — по образцу AccessService.LogAsync из Teams_analyz.
Каждый логин (успешный и неудачный) и каждое изменение ИИ-подключений
пишется сюда одной функцией, чтобы формат записи не расходился по коду.
"""

from .db import get_conn


def log(actor: str, action: str, outcome: str, ip: str | None = None, message: str | None = None) -> None:
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO access_log (actor, action, outcome, ip, message) VALUES (?, ?, ?, ?, ?)",
            (actor, action, outcome, ip, message),
        )
        conn.commit()
    finally:
        conn.close()


def recent(limit: int = 100) -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT id, at, actor, action, outcome, ip, message FROM access_log ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
