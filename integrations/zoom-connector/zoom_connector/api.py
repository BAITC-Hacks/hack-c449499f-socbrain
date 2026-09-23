from contextlib import asynccontextmanager
import json
from pathlib import Path
import secrets

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.security import APIKeyHeader

from .config import Settings
from .events import recording_job
from .security import json_body, validation_response, verify_webhook
from .store import Store

auth = APIKeyHeader(name="X-API-Key", auto_error=False)


def create_app(settings=None, store=None):
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app):
        settings.validate("api")
        app.state.store = store or Store(settings.data_dir)
        yield

    app = FastAPI(title="Jinalys AI Zoom Connector", version="0.1.0", lifespan=lifespan,
                  description="Zoom Cloud Recording, calendar and RTMS event connector")

    def authorize(value=Depends(auth)):
        if not value or not secrets.compare_digest(value.encode(), settings.api_key.encode()):
            raise HTTPException(401, "Invalid API key")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/webhooks/zoom")
    async def zoom_webhook(request: Request, x_zm_request_timestamp: str | None = Header(None),
                           x_zm_signature: str | None = Header(None)):
        raw = await request.body()
        try:
            event = json_body(raw)
        except ValueError as error:
            raise HTTPException(400, str(error)) from None
        if event.get("event") == "endpoint.url_validation":
            plain = str((event.get("payload") or {}).get("plainToken") or "")
            if not plain:
                raise HTTPException(400, "Missing validation token")
            return validation_response(settings.webhook_secret, plain)
        if not verify_webhook(settings.webhook_secret, x_zm_request_timestamp, x_zm_signature, raw):
            raise HTTPException(401, "Invalid or expired Zoom webhook signature")
        name, payload = event.get("event"), event.get("payload") or {}
        if name == "recording.completed":
            try:
                job = recording_job(event, settings.recording_types)
            except ValueError as error:
                raise HTTPException(400, str(error)) from None
            if job:
                app.state.store.enqueue_recording(job)
        elif name == "meeting.started":
            meeting = payload.get("object") or {}
            app.state.store.remember_meeting(meeting)
            if settings.rtms_auto_start and meeting.get("id"):
                app.state.store.enqueue_rtms_start(meeting["id"])
        elif name == "meeting.rtms_started" and settings.rtms_enabled:
            if payload.get("meeting_uuid") and payload.get("rtms_stream_id"):
                app.state.store.enqueue_rtms(payload)
        elif name == "meeting.rtms_stopped" and payload.get("rtms_stream_id"):
            app.state.store.stop_rtms(payload["rtms_stream_id"])
        return {"status": "accepted"}

    secured = [Depends(authorize)]

    @app.get("/api/zoom/calendar", dependencies=secured)
    def calendar(user_id: str | None = None):
        return {"meetings": app.state.store.calendar(user_id)}

    @app.get("/api/zoom/recordings", dependencies=secured)
    def recordings(limit: int = Query(100, ge=1, le=1000)):
        return {"jobs": app.state.store.recordings(limit)}

    @app.get("/api/zoom/rtms", dependencies=secured)
    def rtms_streams(limit: int = Query(100, ge=1, le=1000)):
        return {"streams": app.state.store.rtms(limit)}

    @app.get("/api/zoom/rtms/{stream_id}/transcript", dependencies=secured)
    def transcript(stream_id: str, limit: int = Query(1000, ge=1, le=10000)):
        if len(stream_id) != 32 or any(ch not in "0123456789abcdef" for ch in stream_id):
            raise HTTPException(404, "Stream not found")
        path = Path(settings.data_dir) / (stream_id + ".transcript.jsonl")
        if not path.is_file():
            raise HTTPException(404, "Transcript not available")
        rows = []
        with path.open(encoding="utf-8") as source:
            for line in source:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return {"stream_id": stream_id, "items": rows[-limit:]}

    return app


app = create_app()
