from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3


def now_text():
    return datetime.now(timezone.utc).isoformat()


def safe_id(value):
    return hashlib.sha256(str(value).encode()).hexdigest()[:32]


class Store:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.db_path = self.directory / "zoom.sqlite3"
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS recording_jobs (
                    id TEXT PRIMARY KEY, meeting_uuid TEXT NOT NULL, title TEXT NOT NULL,
                    meeting_date TEXT NOT NULL, filename TEXT NOT NULL, download_url TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
                    detail TEXT NOT NULL DEFAULT '', result TEXT, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS calendar (
                    user_id TEXT NOT NULL, meeting_key TEXT NOT NULL, meeting_id TEXT,
                    start_time TEXT, data TEXT NOT NULL, refreshed_at TEXT NOT NULL,
                    PRIMARY KEY(user_id, meeting_key)
                );
                CREATE TABLE IF NOT EXISTS meeting_meta (
                    meeting_id TEXT PRIMARY KEY, data TEXT NOT NULL, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS rtms_streams (
                    id TEXT PRIMARY KEY, stream_id TEXT UNIQUE NOT NULL, meeting_uuid TEXT NOT NULL,
                    meeting_id TEXT, title TEXT NOT NULL, meeting_date TEXT NOT NULL,
                    payload TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending',
                    detail TEXT NOT NULL DEFAULT '', result TEXT, updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS rtms_actions (
                    meeting_id TEXT PRIMARY KEY, status TEXT NOT NULL DEFAULT 'pending',
                    attempts INTEGER NOT NULL DEFAULT 0, detail TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL
                );
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.db_path, timeout=20)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def enqueue_recording(self, item):
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO recording_jobs"
                       "(id,meeting_uuid,title,meeting_date,filename,download_url,updated_at) VALUES(?,?,?,?,?,?,?)",
                       (item["id"], item["meeting_uuid"], item["title"], item["meeting_date"],
                        item["filename"], item["download_url"], now_text()))
            return db.execute("SELECT * FROM recording_jobs WHERE id=?", (item["id"],)).fetchone()["status"]

    def claim_recording(self, max_attempts=8):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM recording_jobs WHERE status IN ('pending','retry') AND attempts<? "
                             "ORDER BY updated_at LIMIT 1", (max_attempts,)).fetchone()
            if row:
                db.execute("UPDATE recording_jobs SET status='processing',attempts=attempts+1,updated_at=? WHERE id=?",
                           (now_text(), row["id"]))
        return dict(row) if row else None

    def set_recording(self, key, status, detail="", result=None):
        with self.connect() as db:
            db.execute("UPDATE recording_jobs SET status=?,detail=?,result=?,updated_at=? WHERE id=?",
                       (status, detail[:500], json.dumps(result) if result is not None else None, now_text(), key))

    def recordings(self, limit=100):
        with self.connect() as db:
            rows = db.execute("SELECT id,meeting_uuid,title,meeting_date,filename,status,attempts,detail,result,updated_at "
                              "FROM recording_jobs ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
        return [self._decode(row) for row in rows]

    def replace_calendar(self, user_id, meetings):
        refreshed = now_text()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM calendar WHERE user_id=?", (user_id,))
            for meeting in meetings:
                key = str(meeting.get("uuid") or meeting.get("id")) + ":" + str(
                    meeting.get("occurrence_id") or meeting.get("start_time") or "")
                db.execute("INSERT INTO calendar(user_id,meeting_key,meeting_id,start_time,data,refreshed_at) "
                           "VALUES(?,?,?,?,?,?)", (user_id, key, str(meeting.get("id") or ""),
                           str(meeting.get("start_time") or ""), json.dumps(meeting, ensure_ascii=False), refreshed))

    def calendar(self, user_id=None):
        with self.connect() as db:
            if user_id:
                rows = db.execute("SELECT user_id,data,refreshed_at FROM calendar WHERE user_id=? ORDER BY start_time",
                                  (user_id,)).fetchall()
            else:
                rows = db.execute("SELECT user_id,data,refreshed_at FROM calendar ORDER BY start_time").fetchall()
        return [{"user_id": row["user_id"], "refreshed_at": row["refreshed_at"],
                 **json.loads(row["data"])} for row in rows]

    def remember_meeting(self, data):
        meeting_id = str(data.get("id") or "")
        if not meeting_id:
            return
        with self.connect() as db:
            db.execute("INSERT INTO meeting_meta(meeting_id,data,updated_at) VALUES(?,?,?) "
                       "ON CONFLICT(meeting_id) DO UPDATE SET data=excluded.data,updated_at=excluded.updated_at",
                       (meeting_id, json.dumps(data, ensure_ascii=False), now_text()))

    def meeting(self, meeting_id):
        with self.connect() as db:
            row = db.execute("SELECT data FROM meeting_meta WHERE meeting_id=?", (str(meeting_id),)).fetchone()
        return json.loads(row["data"]) if row else {}

    def enqueue_rtms(self, payload):
        stream_id = str(payload["rtms_stream_id"])
        meeting_id = str(payload.get("meeting_id") or "")
        meta = self.meeting(meeting_id)
        date = str(meta.get("start_time") or now_text())[:10]
        item_id = safe_id(stream_id)
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO rtms_streams"
                "(id,stream_id,meeting_uuid,meeting_id,title,meeting_date,payload,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (item_id, stream_id, str(payload["meeting_uuid"]), meeting_id,
                 str(meta.get("topic") or f"Zoom meeting {meeting_id}")[:300], date,
                 json.dumps(payload), now_text()))
        return item_id

    def stop_rtms(self, stream_id):
        with self.connect() as db:
            db.execute("UPDATE rtms_streams SET status='stopping',updated_at=? WHERE stream_id=? "
                       "AND status NOT IN ('delivered','finished','error')", (now_text(), str(stream_id)))

    def pending_rtms(self):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM rtms_streams WHERE status='pending' ORDER BY updated_at").fetchall()
        return [self._decode(row, payload=True) for row in rows]

    def stopping_rtms(self):
        with self.connect() as db:
            rows = db.execute("SELECT * FROM rtms_streams WHERE status='stopping'").fetchall()
        return [self._decode(row, payload=True) for row in rows]

    def set_rtms(self, key, status, detail="", result=None):
        with self.connect() as db:
            db.execute("UPDATE rtms_streams SET status=?,detail=?,result=?,updated_at=? WHERE id=?",
                       (status, detail[:500], json.dumps(result) if result is not None else None, now_text(), key))

    def rtms(self, limit=100):
        with self.connect() as db:
            rows = db.execute("SELECT id,stream_id,meeting_uuid,meeting_id,title,meeting_date,status,detail,result,updated_at "
                              "FROM rtms_streams ORDER BY updated_at DESC LIMIT ?", (limit,)).fetchall()
        return [self._decode(row) for row in rows]

    def enqueue_rtms_start(self, meeting_id):
        with self.connect() as db:
            db.execute("INSERT INTO rtms_actions(meeting_id,updated_at) VALUES(?,?) ON CONFLICT(meeting_id) DO NOTHING",
                       (str(meeting_id), now_text()))

    def claim_rtms_start(self):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM rtms_actions WHERE status IN ('pending','retry') AND attempts<5 "
                             "ORDER BY updated_at LIMIT 1").fetchone()
            if row:
                db.execute("UPDATE rtms_actions SET status='processing',attempts=attempts+1,updated_at=? WHERE meeting_id=?",
                           (now_text(), row["meeting_id"]))
        return dict(row) if row else None

    def set_rtms_start(self, meeting_id, status, detail=""):
        with self.connect() as db:
            db.execute("UPDATE rtms_actions SET status=?,detail=?,updated_at=? WHERE meeting_id=?",
                       (status, detail[:500], now_text(), str(meeting_id)))

    def recover_recordings(self):
        with self.connect() as db:
            db.execute("UPDATE recording_jobs SET status='retry',detail='Recovered after worker restart' "
                       "WHERE status='processing'")
            db.execute("UPDATE rtms_actions SET status='retry',detail='Recovered after worker restart' "
                       "WHERE status='processing'")

    def recover_rtms(self):
        with self.connect() as db:
            db.execute("UPDATE rtms_streams SET status='pending',detail='Reconnecting after RTMS worker restart' "
                       "WHERE status='running'")

    @staticmethod
    def _decode(row, payload=False):
        value = dict(row)
        if value.get("result"):
            value["result"] = json.loads(value["result"])
        if payload and value.get("payload"):
            value["payload"] = json.loads(value["payload"])
        else:
            value.pop("payload", None)
        value.pop("download_url", None)
        return value
