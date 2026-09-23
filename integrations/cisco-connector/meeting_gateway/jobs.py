"""Durable single-worker journal, separate from the receiving application's DB."""
import json
from pathlib import Path
import sqlite3


class Jobs:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "jobs.sqlite3"
        with self.connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS jobs (id TEXT PRIMARY KEY, event TEXT NOT NULL, "
                         "status TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '', result TEXT)")

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return closing_connection(conn)

    def sync(self, events):
        with self.connect() as conn:
            for event in events:
                conn.execute("INSERT INTO jobs(id,event,status) VALUES(?,?,'pending') "
                             "ON CONFLICT(id) DO UPDATE SET event=excluded.event,status='pending',detail='' "
                             "WHERE jobs.status IN ('pending','cancelled')",
                             (event["id"], json.dumps(event)))
            ids = {event["id"] for event in events}
            for row in conn.execute("SELECT id FROM jobs WHERE status='pending'"):
                if row["id"] not in ids:
                    conn.execute("UPDATE jobs SET status='cancelled', detail='Removed from schedule' WHERE id=?", (row["id"],))

    def set(self, key, status, detail="", result=None):
        with self.connect() as conn:
            conn.execute("UPDATE jobs SET status=?,detail=?,result=? WHERE id=?",
                         (status, detail, json.dumps(result) if result is not None else None, key))

    def all(self, limit=200):
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM jobs ORDER BY rowid DESC LIMIT ?", (limit,)).fetchall()
        return [{**dict(row), "event": json.loads(row["event"]),
                 "result": json.loads(row["result"]) if row["result"] else None} for row in rows]

    def recover(self, idempotent=False):
        with self.connect() as conn:
            conn.execute("UPDATE jobs SET status='failed',detail='Worker interrupted; recording kept for inspection' "
                         "WHERE status='recording'")
            conn.execute("UPDATE jobs SET status=?,detail=? WHERE status='uploading'",
                         ("recorded" if idempotent else "delivery_unknown",
                          "Retry with idempotency key" if idempotent else "Upload interrupted; check receiver before retry"))


class closing_connection:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self.conn

    def __exit__(self, kind, value, tb):
        try:
            if kind is None:
                self.conn.commit()
            else:
                self.conn.rollback()
        finally:
            self.conn.close()
