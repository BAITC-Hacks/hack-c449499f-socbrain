from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
import sqlite3

from fastapi.testclient import TestClient
import pytest

from app.receiver import create_app
from app.ingest_worker import process_one
from app.stt.base import TranscriptResult, TranscriptSegment

KEY = "test-key-" + "x" * 32
AUTH = {"X-API-Key": KEY, "Idempotency-Key": "test-meeting-occurrence"}
DATA = {"title": "Cisco meeting", "meeting_date": "2026-09-23", "participants_notified": "true", "source": "cms"}


def send(api, audio=b"complete-wav", headers=AUTH):
    return api.post("/api/recordings", headers=headers, data=DATA, files={"file": ("../../recording.wav", audio, "audio/wav")})


def test_completed_upload_enters_queue_and_is_transcribed_locally(tmp_path):
    app = create_app(KEY, tmp_path)
    with TestClient(app) as api:
        response = send(api)
        assert response.status_code == 201
        key = response.json()["id"]
        def transcribe(path):
            assert path.parent == tmp_path
            assert path.read_bytes() == b"complete-wav"
            return TranscriptResult("ru", [TranscriptSegment(0, 2, "Проверка")])
        assert process_one(app.state.store, SimpleNamespace(transcribe=transcribe))
        result = api.get("/api/recordings/" + key, headers=AUTH).json()
        assert result["status"] == "done"
        assert result["source"] == "cms"
        assert result["result"]["segments"][0]["text"] == "Проверка"
        assert not process_one(app.state.store, None)


def test_idempotent_upload_returns_same_id_and_no_extra_file(tmp_path):
    with TestClient(create_app(KEY, tmp_path)) as api:
        first, second = send(api), send(api)
        assert first.json()["id"] == second.json()["id"]
        assert second.json()["duplicate"] is True
        assert len(list(tmp_path.glob("*.wav"))) == 1
        assert send(api, audio=b"other audio").status_code == 409
        assert len(list(tmp_path.glob("*.wav"))) == 1


@pytest.mark.parametrize("payload,status", [(b"", 400), (b"x" * 11, 413)])
def test_incomplete_upload_not_visible_to_worker(tmp_path, payload, status):
    app = create_app(KEY, tmp_path, max_bytes=10)
    with TestClient(app) as api:
        assert send(api, payload).status_code == status
        assert app.state.store.claim() is None
        assert not list(tmp_path.glob("*.wav"))


def test_auth_notice_and_error_redaction(tmp_path):
    app = create_app(KEY, tmp_path)
    with TestClient(app) as api:
        assert send(api, headers={}).status_code == 401
        rejected = api.post("/api/recordings", headers=AUTH, data={**DATA, "participants_notified": "false"},
                            files={"file": ("audio.wav", b"audio")})
        assert rejected.status_code == 400
        key = send(api).json()["id"]
        def failed(_):
            raise RuntimeError("SECRET")
        process_one(app.state.store, SimpleNamespace(transcribe=failed))
        response = api.get("/api/recordings/" + key, headers=AUTH)
        assert response.json()["status"] == "error"
        assert "SECRET" not in response.text


def test_existing_database_gains_source_without_losing_idempotency(tmp_path):
    path = tmp_path / "ingest.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE recordings (id TEXT PRIMARY KEY, source_key TEXT UNIQUE, title TEXT NOT NULL, "
                   "meeting_date TEXT NOT NULL, filename TEXT NOT NULL, sha256 TEXT NOT NULL, "
                   "status TEXT NOT NULL DEFAULT 'queued', "
                   "result TEXT, error TEXT, created_at TEXT NOT NULL)")
    app = create_app(KEY, tmp_path)
    with TestClient(app) as api:
        first = send(api)
        assert first.status_code == 201
        assert send(api).json()["id"] == first.json()["id"]
        result = api.get("/api/recordings/" + first.json()["id"], headers=AUTH).json()
        assert result["source"] == "cms"
