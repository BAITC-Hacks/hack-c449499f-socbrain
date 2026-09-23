import os
import re
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import db
from ..config import LLM_PRESETS, is_external_url, settings
from ..export import docx_export, pdf_export

# Фронтенд лежит в корне репозитория (frontend/); в Docker-образе — /srv/frontend.
FRONTEND = Path(os.getenv("FRONTEND_DIR") or Path(__file__).resolve().parents[3] / "frontend")
ALLOWED_SUFFIXES = {".mp3", ".wav", ".m4a", ".ogg", ".opus", ".flac", ".webm", ".mp4", ".mkv", ".mov", ".aac", ".wma"}

@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(title="Protocol AI", version="0.1.0", lifespan=lifespan)


@app.get("/", include_in_schema=False)
def index() -> RedirectResponse:
    return RedirectResponse("/index.html")


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/api/config")
def public_config() -> dict:
    """Что видит пользователь о конфигурации: какая LLM и уходит ли текст за контур."""
    stt = os.getenv("STT_PROVIDER", "local").lower()
    return {"llm_provider": settings.llm_provider, "llm_model": settings.llm_model,
            "llm_external": settings.llm_external and settings.llm_provider != "none",
            "stt_provider": stt, "stt_external": stt == "external",
            "whisper_model": settings.whisper_model if stt == "local" else "whisper-1"}


@app.get("/api/llm/providers")
def llm_providers() -> dict:
    """Шаблоны подключения LLM для страницы настроек. Значения ключей не отдаются — только задан ли ключ."""
    return {
        "active": settings.llm_provider,
        "active_base_url": settings.llm_base_url,
        "active_model": settings.llm_model,
        "active_external": settings.llm_external,
        "presets": [{**{k: v for k, v in preset.items()}, "id": pid,
                     "external": is_external_url(preset["base_url"]) and pid != "none",
                     "key_set": bool(os.getenv(preset["key_env"]))}
                    for pid, preset in LLM_PRESETS.items()],
    }


@app.post("/api/llm/check")
def llm_check() -> dict:
    """Проверить текущее подключение LLM: адрес, ключ, модель, структурированный ответ."""
    from ..pipeline import llm
    return llm.check()


@app.get("/api/stats")
def stats() -> dict:
    """Цифры для дашборда: совещания, поручения по статусам, языки совещаний."""
    tasks = db.list_tasks()
    by_state = {s: sum(1 for t in tasks if t["state"] == s) for s in ("in_progress", "overdue", "done")}
    languages = {r["language"] or "": r["n"] for r in db.rows(
        "SELECT language, COUNT(*) AS n FROM meetings WHERE status = 'done' GROUP BY language")}
    month_ago = (date.today() - timedelta(days=30)).isoformat()
    meetings_month = db.row("SELECT COUNT(*) AS n FROM meetings WHERE meeting_date >= ?", month_ago)["n"]
    return {"meetings_month": meetings_month, "tasks": by_state, "languages": languages}


# --- совещания -----------------------------------------------------------------

@app.post("/api/meetings", status_code=201)
async def upload_meeting(
    file: UploadFile = File(...),
    title: str = Form(...),
    meeting_date: date | None = Form(None),
    num_speakers: int = Form(0),
    participants: str = Form(""),
    consent: bool = Form(False),
) -> dict:
    if not consent:
        raise HTTPException(400, "Участники должны быть уведомлены о записи и ИИ-транскрибации")
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(400, f"Неподдерживаемый формат {suffix!r}")

    meeting_date = meeting_date or date.today()
    meeting_id = db.create_meeting(title.strip(), meeting_date.isoformat(), "", consent, max(num_speakers, 0),
                                   participants.strip())
    filename = f"{meeting_id}{suffix}"
    with open(settings.upload_dir / filename, "wb") as out:
        while chunk := await file.read(1024 * 1024):
            out.write(chunk)
    db.execute("UPDATE meetings SET filename = ? WHERE id = ?", filename, meeting_id)
    return {"id": meeting_id}


@app.get("/api/meetings")
def list_meetings() -> list[dict]:
    return db.rows(
        "SELECT m.id, m.title, m.meeting_date, m.status, m.stage, m.error, m.duration, m.language, m.created_at,"
        " m.summary, m.participants,"
        " (SELECT COUNT(*) FROM tasks t WHERE t.meeting_id = m.id) AS task_count,"
        " (SELECT COUNT(*) FROM speakers s WHERE s.meeting_id = m.id) AS speaker_count"
        " FROM meetings m ORDER BY m.created_at DESC"
    )


@app.get("/api/meetings/{meeting_id}")
def get_meeting(meeting_id: str) -> dict:
    meeting = db.meeting_bundle(meeting_id)
    if not meeting:
        raise HTTPException(404)
    return meeting


@app.post("/api/meetings/{meeting_id}/reprocess")
def reprocess(meeting_id: str, mode: str = "full") -> dict:
    """mode=full — заново всё (ASR, диаризация, анализ); mode=llm — только анализ готовой стенограммы."""
    meeting = db.row("SELECT id, duration FROM meetings WHERE id = ?", meeting_id)
    if not meeting:
        raise HTTPException(404)
    if mode == "llm" and not db.row("SELECT 1 FROM segments WHERE meeting_id = ? LIMIT 1", meeting_id):
        raise HTTPException(400, "Стенограммы ещё нет — нужна полная обработка")
    stage = "llm_only" if mode == "llm" else None
    db.execute("UPDATE meetings SET status = 'queued', stage = ?, error = NULL WHERE id = ?", stage, meeting_id)
    return {"status": "queued", "mode": mode}


@app.delete("/api/meetings/{meeting_id}", status_code=204)
def delete_meeting(meeting_id: str) -> None:
    meeting = db.row("SELECT filename FROM meetings WHERE id = ?", meeting_id)
    if not meeting:
        raise HTTPException(404)
    db.execute("DELETE FROM meetings WHERE id = ?", meeting_id)
    if meeting["filename"]:
        (settings.upload_dir / meeting["filename"]).unlink(missing_ok=True)


class MeetingUpdate(BaseModel):
    title: str | None = None
    participants: str | None = None


@app.patch("/api/meetings/{meeting_id}")
def update_meeting(meeting_id: str, body: MeetingUpdate) -> dict:
    """Правка карточки. Новые участники применятся при «Переанализировать»."""
    changes = body.model_dump(exclude_unset=True, exclude_none=True)
    if not changes:
        raise HTTPException(400, "Нет изменений")
    assignments = ", ".join(f"{column} = ?" for column in changes)
    db.execute(f"UPDATE meetings SET {assignments} WHERE id = ?", *changes.values(), meeting_id)
    return {"ok": True}


class SpeakerUpdate(BaseModel):
    name: str
    role: str = ""


@app.put("/api/meetings/{meeting_id}/speakers/{label}")
def update_speaker(meeting_id: str, label: str, body: SpeakerUpdate) -> dict:
    db.execute("INSERT INTO speakers (meeting_id, label, name, role) VALUES (?, ?, ?, ?)"
               " ON CONFLICT (meeting_id, label) DO UPDATE SET name = excluded.name, role = excluded.role",
               meeting_id, label, body.name.strip(), body.role.strip())
    return {"ok": True}


def _export_response(meeting_id: str, content_builder, media_type: str, ext: str) -> Response:
    meeting = db.meeting_bundle(meeting_id)
    if not meeting or meeting["status"] != "done":
        raise HTTPException(404, "Протокол ещё не готов")
    name = re.sub(r"[^\w\-]+", "_", f"Протокол_{meeting['meeting_date']}_{meeting['title']}")[:80] + ext
    return Response(content_builder(meeting), media_type=media_type,
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(name)}"})


@app.get("/api/meetings/{meeting_id}/export.docx")
def export_docx(meeting_id: str) -> Response:
    return _export_response(meeting_id, docx_export.build,
                            "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx")


@app.get("/api/meetings/{meeting_id}/export.pdf")
def export_pdf(meeting_id: str) -> Response:
    return _export_response(meeting_id, pdf_export.build, "application/pdf", ".pdf")


# --- поручения -----------------------------------------------------------------

@app.get("/api/tasks")
def list_tasks(state: str | None = None) -> list[dict]:
    tasks = db.list_tasks()
    return [t for t in tasks if t["state"] == state] if state else tasks


class TaskUpdate(BaseModel):
    description: str | None = None
    assignee: str | None = None
    due_date: date | None = None
    status: str | None = None


@app.patch("/api/tasks/{task_id}")
def update_task(task_id: int, body: TaskUpdate) -> dict:
    changes = body.model_dump(exclude_unset=True)
    if "status" in changes and changes["status"] not in ("in_progress", "done"):
        raise HTTPException(400, "status: in_progress | done")
    if "due_date" in changes and changes["due_date"]:
        changes["due_date"] = changes["due_date"].isoformat()
    if not changes:
        raise HTTPException(400, "Нет изменений")
    assignments = ", ".join(f"{column} = ?" for column in changes)
    db.execute(f"UPDATE tasks SET {assignments} WHERE id = ?", *changes.values(), task_id)
    return {"ok": True}


@app.get("/api/reminders")
def reminders() -> dict:
    """Сценарий 2: поручения с приближающимся или просроченным сроком (для рассылки напоминаний)."""
    today = date.today()
    horizon = today + timedelta(days=settings.remind_days_before)
    due_soon, overdue = [], []
    for task in db.list_tasks():
        if task["status"] == "done" or not task["due_date"]:
            continue
        due = date.fromisoformat(task["due_date"])
        if due < today:
            overdue.append(task)
        elif due <= horizon:
            due_soon.append(task)
    return {"today": today.isoformat(), "due_soon": due_soon, "overdue": overdue}


# Статика фронтенда — последней, чтобы не перекрывать /api.
if FRONTEND.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
