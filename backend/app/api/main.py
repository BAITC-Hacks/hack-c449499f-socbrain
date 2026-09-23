import os
import re
import smtplib
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .. import db, vault
from ..config import LLM_PRESETS, SECRETS, SECTIONS, coerce, is_external_url, load_overrides, settings
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
    stt = settings.stt_provider
    return {"llm_provider": settings.llm_provider, "llm_model": settings.llm_model,
            "llm_external": settings.llm_external and settings.llm_provider != "none",
            "stt_provider": stt, "stt_external": stt == "external",
            "whisper_model": settings.whisper_model if stt == "local" else "whisper-1",
            "appearance": settings.values["appearance"]}


# --- настройки -----------------------------------------------------------------

@app.get("/api/settings")
def get_settings() -> dict:
    """Действующие значения всех разделов + где они заданы + какие секреты есть в .env (без значений)."""
    overrides = load_overrides(settings.db_path)
    fields = {
        section: {name: {"type": kind, "env": env, "default": default, "choices": choices,
                         "source": "интерфейс" if overrides.get(section, {}).get(name) not in (None, "")
                         else ".env" if os.getenv(env) else "по умолчанию"}
                  for name, (kind, env, default, choices) in section_fields.items()}
        for section, section_fields in SECTIONS.items()
    }
    return {"values": settings.values, "fields": fields, "updated_at": db.settings_updated_at(),
            "secrets": {section: {env: vault.status(settings.data_dir, env, settings.secret_host(env)) for env in envs}
                        for section, envs in SECRETS.items()},
            "whisper_model": settings.whisper_model}


@app.put("/api/settings/{section}")
def put_settings(section: str, body: dict) -> dict:
    """Сохранить раздел. Пустая строка в поле = вернуть значение из .env / по умолчанию."""
    if section not in SECTIONS:
        raise HTTPException(404, f"Нет раздела {section!r}")
    fields = SECTIONS[section]
    unknown = set(body) - set(fields)
    if unknown:
        raise HTTPException(400, f"Неизвестные поля: {', '.join(sorted(unknown))}")
    saved = load_overrides(settings.db_path).get(section, {})
    errors = {}
    for name, raw in body.items():
        kind, _, _, choices = fields[name]
        if raw in (None, ""):
            saved.pop(name, None)
            continue
        try:
            saved[name] = coerce(kind, raw, choices)
        except ValueError as exc:
            errors[name] = str(exc) or "неверное значение"
    if errors:
        raise HTTPException(400, {"errors": errors})
    db.save_settings(section, saved)
    settings.reload()
    return {"values": settings.values[section]}


class SecretValue(BaseModel):
    value: str


ALLOWED_SECRETS = {name for names in SECRETS.values() for name in names}


@app.put("/api/secrets/{name}")
def put_secret(name: str, body: SecretValue) -> dict:
    """Сохранить ключ/пароль из интерфейса. Значение шифруется и больше никогда не отдаётся —
    только статус «задан, …ab12». Ключ привязывается к хосту, куда он будет отправляться."""
    if name not in ALLOWED_SECRETS:
        raise HTTPException(404, f"Неизвестный секрет {name!r}")
    value = body.value.strip()
    if not value:
        raise HTTPException(400, "Пустое значение — для удаления используйте DELETE")
    if len(value) > 4096 or any(c in value for c in "\r\n"):
        raise HTTPException(400, "Недопустимое значение")
    host = settings.secret_host(name)
    if name == "SMTP_PASSWORD" and not host:
        raise HTTPException(400, "Сначала сохраните адрес SMTP-сервера — пароль привязывается к нему")
    vault.set_secret(settings.data_dir, name, value, host)
    settings.reload()
    return {"status": vault.status(settings.data_dir, name, host)}


@app.delete("/api/secrets/{name}")
def delete_secret(name: str) -> dict:
    """Удалить значение, введённое в интерфейсе (значение из .env, если есть, снова станет действующим)."""
    if name not in ALLOWED_SECRETS:
        raise HTTPException(404, f"Неизвестный секрет {name!r}")
    vault.clear_secret(settings.data_dir, name)
    settings.reload()
    return {"status": vault.status(settings.data_dir, name, settings.secret_host(name))}


@app.post("/api/settings/mail/check")
def check_mail() -> dict:
    """Проверить SMTP: соединение, шифрование, вход. Письмо не отправляется."""
    mail = settings.values["mail"]
    steps = []
    if not mail["host"]:
        return {"ok": False, "steps": steps, "error": "Не указан адрес сервера"}
    try:
        smtp_cls = smtplib.SMTP_SSL if mail["security"] == "ssl" else smtplib.SMTP
        with smtp_cls(mail["host"], mail["port"], timeout=10) as smtp:
            steps.append(f"соединение с {mail['host']}:{mail['port']}")
            smtp.ehlo()
            if mail["security"] == "starttls":
                smtp.starttls()
                smtp.ehlo()
                steps.append("STARTTLS")
            if mail["username"]:
                password = settings.secret("SMTP_PASSWORD", mail["host"])
                if not password:
                    return {"ok": False, "steps": steps,
                            "error": "Указан логин, но пароль не задан — введите его в форме выше"}
                smtp.login(mail["username"], password)
                steps.append("вход выполнен")
    except (OSError, smtplib.SMTPException) as exc:
        return {"ok": False, "steps": steps, "error": f"{type(exc).__name__}: {exc}"}
    return {"ok": True, "steps": steps, "error": None}


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
                     "key_set": vault.status(settings.data_dir, preset["key_env"],
                                             settings.secret_host(preset["key_env"]))["usable"]}
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
    meeting = db.row("SELECT id, duration, filename FROM meetings WHERE id = ?", meeting_id)
    if not meeting:
        raise HTTPException(404)
    if mode != "llm" and not meeting["filename"]:
        raise HTTPException(400, "Аудио удалено по сроку хранения — доступен только «Переанализировать»")
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
