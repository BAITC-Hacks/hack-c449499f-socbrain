from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import hmac
import json
from pathlib import Path
from types import SimpleNamespace
import wave

from fastapi.testclient import TestClient
import httpx

from zoom_connector.api import create_app
from zoom_connector.config import Settings
from zoom_connector.events import recording_job
from zoom_connector.rtms_worker import SessionFiles
from zoom_connector.security import webhook_signature
from zoom_connector.store import Store
from zoom_connector.worker import download_recording, process_recording
from zoom_connector.zoom_api import ZoomAPI

KEY = "k" * 40
SECRET = "webhook-secret-value"


def config(tmp_path):
    return Settings("account", "client", "secret", SECRET, KEY, tmp_path, ("me",), 300,
        ("AUDIO_ONLY", "M4A", "MP4"), 1024 * 1024, True, "https://socbrain.test/api/recordings",
        "a" * 40, False, "", True, "rtms-client", "rtms-secret", True, 0.1)


def signed(payload, stamp=1_800_000_000):
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return raw, {"x-zm-request-timestamp": str(stamp),
                 "x-zm-signature": webhook_signature(SECRET, stamp, raw)}


def recording_event():
    return {"event": "recording.completed", "payload": {"object": {"id": 123, "uuid": "uuid-1",
        "topic": "Планёрка", "start_time": "2026-09-23T09:00:00Z", "recording_files": [
            {"id": "video", "file_type": "MP4", "recording_type": "shared_screen", "status": "completed",
             "download_url": "https://us02web.zoom.us/rec/download/video"},
            {"id": "audio", "file_type": "M4A", "recording_type": "audio_only", "status": "completed",
             "download_url": "https://us02web.zoom.us/rec/download/audio"}]}}}


def test_validation_signature_and_recording_queue(tmp_path, monkeypatch):
    monkeypatch.setattr("zoom_connector.security.time.time", lambda: 1_800_000_000)
    store = Store(tmp_path)
    with TestClient(create_app(config(tmp_path), store)) as api:
        response = api.post("/webhooks/zoom", json={"event": "endpoint.url_validation",
                            "payload": {"plainToken": "plain"}})
        assert response.json() == {"plainToken": "plain", "encryptedToken": hmac.new(
            SECRET.encode(), b"plain", hashlib.sha256).hexdigest()}
        raw, headers = signed(recording_event())
        assert api.post("/webhooks/zoom", content=raw, headers=headers).status_code == 200
        jobs = api.get("/api/zoom/recordings", headers={"X-API-Key": KEY}).json()["jobs"]
        assert len(jobs) == 1 and jobs[0]["filename"].endswith(".m4a")
        assert api.post("/webhooks/zoom", content=raw, headers=headers).status_code == 200
        assert len(store.recordings()) == 1
        assert api.post("/webhooks/zoom", content=raw).status_code == 401


def test_meeting_events_queue_rtms_and_live_transcript(tmp_path, monkeypatch):
    monkeypatch.setattr("zoom_connector.security.time.time", lambda: 1_800_000_000)
    store = Store(tmp_path)
    with TestClient(create_app(config(tmp_path), store)) as api:
        for event in [
            {"event": "meeting.started", "payload": {"object": {"id": 77, "topic": "Live", "start_time": "2026-09-23T10:00:00Z"}}},
            {"event": "meeting.rtms_started", "payload": {"meeting_id": 77, "meeting_uuid": "mu", "rtms_stream_id": "stream"}},
        ]:
            raw, headers = signed(event)
            assert api.post("/webhooks/zoom", content=raw, headers=headers).status_code == 200
        row = store.rtms()[0]
        (tmp_path / (row["id"] + ".transcript.jsonl")).write_text(
            json.dumps({"user_name": "Иван", "text": "Привет"}, ensure_ascii=False) + "\n", encoding="utf-8")
        result = api.get(f"/api/zoom/rtms/{row['id']}/transcript", headers={"X-API-Key": KEY}).json()
        assert result["items"][0]["user_name"] == "Иван"
        raw, headers = signed({"event": "meeting.rtms_stopped", "payload": {"rtms_stream_id": "stream"}})
        api.post("/webhooks/zoom", content=raw, headers=headers)
        assert store.stopping_rtms()[0]["id"] == row["id"]


def test_calendar_combines_hosted_and_invited(tmp_path):
    calls = []
    def handler(request):
        calls.append(request.url.path)
        if request.url.path == "/oauth/token":
            return httpx.Response(200, json={"access_token": "token", "expires_in": 3600})
        if request.url.path.endswith("/upcoming_meetings"):
            return httpx.Response(200, json={"meetings": [
            {"id": 1, "uuid": "same", "start_time": "2026-09-24T10:00:00Z"},
            {"id": 2, "uuid": "invited", "start_time": "2026-09-24T11:00:00Z"}]})
        return httpx.Response(200, json={"meetings": [{"id": 1, "uuid": "same", "start_time": "2026-09-24T10:00:00Z"}]})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    api = ZoomAPI(config(tmp_path), client)
    result = api.calendar("person@example.org")
    assert len(result) == 2
    assert next(x for x in result if x["uuid"] == "same")["calendar_sources"] == ["hosted", "invited"]


def test_download_and_delivery_pipeline(tmp_path):
    settings = config(tmp_path)
    job = recording_job(recording_event(), settings.recording_types)
    store = Store(tmp_path)
    store.enqueue_recording(job)
    def handler(request):
        if request.url.path == "/rec/download/audio":
            assert request.headers["authorization"] == "Bearer zoom-token"
            return httpx.Response(302, headers={"location": "https://storage.test/file"})
        assert request.url.host == "storage.test" and "authorization" not in request.headers
        return httpx.Response(200, content=b"audio-data")
    zoom = SimpleNamespace(client=httpx.Client(transport=httpx.MockTransport(handler)), token=lambda: "zoom-token")
    delivered = SimpleNamespace(upload=lambda path, title, date, key, source: {
        "id": "socbrain-id", "bytes": len(path.read_bytes()), "source": source})
    assert process_recording(store, zoom, delivered, settings)
    assert store.recordings()[0]["status"] == "delivered"
    assert store.recordings()[0]["result"]["bytes"] == 10


def test_rtms_files_create_wav_and_named_transcript(tmp_path):
    files = SessionFiles(tmp_path, "a" * 32)
    meta = SimpleNamespace(userId=5, userName="Айгуль")
    files.audio(b"\x01\x00" * 320, 640, 1000, meta)
    files.audio(b"\x02\x00" * 320, 640, 1060, meta)  # includes a 40 ms silence gap
    files.transcript("Тест".encode(), len("Тест".encode()), 1000, meta)
    files.speaker(1000, 5, "Айгуль")
    files.close()
    with wave.open(str(files.wav_path), "rb") as audio:
        assert audio.getframerate() == 16000 and audio.getnchannels() == 1
        assert audio.getnframes() > 640
    line = json.loads(files.transcript_path.read_text(encoding="utf-8").splitlines()[0])
    assert line["user_name"] == "Айгуль" and line["text"] == "Тест"
