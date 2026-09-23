"""Authenticated HTTP ingress for Cisco recordings; no STT model loaded in the API."""
from contextlib import asynccontextmanager
from datetime import date
import hashlib
import os
from pathlib import Path
import secrets
import sqlite3
from uuid import UUID, uuid4

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.security import APIKeyHeader

from .ingest_store import Store

auth = APIKeyHeader(name="X-API-Key", auto_error=False)


def create_app(api_key=None, directory=None, max_bytes=None):
    key = api_key if api_key is not None else os.getenv("SOCBRAIN_API_KEY", "")
    directory = directory or os.getenv("INGEST_DATA_DIR", "/data")
    max_bytes = max_bytes if max_bytes is not None else int(os.getenv("INGEST_MAX_BYTES", "1073741824"))

    @asynccontextmanager
    async def lifespan(app):
        if len(key) < 32 or max_bytes <= 0:
            raise ValueError("Set SOCBRAIN_API_KEY (32+ characters) and a positive INGEST_MAX_BYTES")
        app.state.store = Store(directory)
        yield

    app = FastAPI(title="SOCBrain Recording Receiver", lifespan=lifespan)

    def authorize(value=Depends(auth)):
        if not value or not secrets.compare_digest(value.encode(), key.encode()):
            raise HTTPException(401, "Invalid API key")

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/api/recordings", dependencies=[Depends(authorize)], status_code=201)
    def upload(file: UploadFile = File(...), title: str = Form(..., min_length=1, max_length=300),
               meeting_date: date = Form(...), participants_notified: bool = Form(False),
               source: str = Form("cms"),
               source_key: str | None = Header(None, alias="Idempotency-Key", min_length=1, max_length=200)):
        path = None
        try:
            if not participants_notified:
                raise HTTPException(400, "Participants must be notified about recording and transcription")
            if not title.strip():
                raise HTTPException(422, "Title must not be blank")
            suffix = Path(file.filename or "").suffix.lower()
            if suffix not in {".wav", ".mp3", ".mp4", ".m4a", ".ogg", ".flac", ".webm", ".opus"}:
                raise HTTPException(400, "Unsupported audio format")
            recording_id = str(uuid4())
            path = app.state.store.directory / (recording_id + suffix)
            digest, size = hashlib.sha256(), 0
            with path.open("xb") as out:
                while chunk := file.file.read(1024 * 1024):
                    size += len(chunk)
                    if size > max_bytes:
                        raise HTTPException(413, "Recording too large")
                    out.write(chunk)
                    digest.update(chunk)
                out.flush()
                os.fsync(out.fileno())
            if size == 0:
                raise HTTPException(400, "Empty recording")
            try:
                app.state.store.insert(recording_id, title.strip(), meeting_date.isoformat(), path.name,
                                       digest.hexdigest(), source_key)
            except sqlite3.IntegrityError:
                existing = app.state.store.source(source_key) if source_key else None
                if not existing:
                    raise
                if (existing["sha256"] != digest.hexdigest() or existing["title"] != title.strip()
                        or existing["meeting_date"] != meeting_date.isoformat()):
                    raise HTTPException(409, "Idempotency key was already used for another recording") from None
                path.unlink()
                path = None
                return {"id": existing["id"], "status": existing["status"], "duplicate": True}
            path = None  # Queue owns the completed file from here.
            return {"id": recording_id, "status": "queued", "duplicate": False}
        finally:
            file.file.close()
            if path is not None:
                path.unlink(missing_ok=True)

    @app.get("/api/recordings/{recording_id}", dependencies=[Depends(authorize)])
    def recording(recording_id: UUID):
        result = app.state.store.get(str(recording_id))
        if result is None:
            raise HTTPException(404, "Recording not found")
        return result

    return app


app = create_app()
