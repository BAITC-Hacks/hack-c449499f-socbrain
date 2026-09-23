"""Durable recording queue; publish a job only after its file is complete."""
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "ingest.sqlite3"
        with self.connect() as conn:
            conn.execute("CREATE TABLE IF NOT EXISTS recordings (id TEXT PRIMARY KEY, source_key TEXT UNIQUE, "
                "title TEXT NOT NULL, meeting_date TEXT NOT NULL, filename TEXT NOT NULL, sha256 TEXT NOT NULL, "
                "status TEXT NOT NULL DEFAULT 'queued', result TEXT, error TEXT, created_at TEXT NOT NULL)")

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=20)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def insert(self, key, title, meeting_date, filename, sha256, source_key):
        with self.connect() as conn:
            conn.execute("INSERT INTO recordings(id,source_key,title,meeting_date,filename,sha256,created_at) "
                         "VALUES(?,?,?,?,?,?,?)", (key, source_key, title, meeting_date, filename, sha256,
                                                  datetime.now(timezone.utc).isoformat()))

    def source(self, key):
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM recordings WHERE source_key=?", (key,)).fetchone()
        return dict(row) if row else None

    def get(self, key):
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM recordings WHERE id=?", (key,)).fetchone()
        if row is None:
            return None
        result = dict(row)
        result.pop("filename")
        result["result"] = json.loads(result["result"]) if result["result"] else None
        return result

    def claim(self):
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM recordings WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
            if row:
                conn.execute("UPDATE recordings SET status='processing',error=NULL WHERE id=?", (row["id"],))
        return dict(row) if row else None

    def finish(self, key, result):
        with self.connect() as conn:
            conn.execute("UPDATE recordings SET status='done',result=?,error=NULL WHERE id=?",
                         (json.dumps(result, ensure_ascii=False), key))

    def fail(self, key):
        with self.connect() as conn:
            conn.execute("UPDATE recordings SET status='error',error='Local transcription failed; check worker' WHERE id=?", (key,))

    def recover(self):
        with self.connect() as conn:
            conn.execute("UPDATE recordings SET status='queued' WHERE status='processing'")
