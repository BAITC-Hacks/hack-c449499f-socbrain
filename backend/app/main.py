"""Первый рабочий срез API: логин с журналом доступа + управление
подключениями ИИ-моделей. Запуск:

    uvicorn app.main:app --reload --port 8000

Дальше сюда же добавятся /meetings и /tasks — пока фронт статичный,
бэкенд поднимается для этих двух функций отдельно.
"""

import tempfile
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

load_dotenv()  # .env — до импорта stt/*, иначе os.getenv в get_provider() видит пустоту

from . import access_log, ai_connections, auth, meetings, tasks_extraction  # noqa: E402
from .db import init_db  # noqa: E402

app = FastAPI(title="Jinalys AI backend")
init_db()

# Фронт пока открывается как file:// (двойной клик по html) — оттуда
# Origin приходит как "null", и обычный allow_origins с конкретным
# адресом его не пропустит. Для прототипа разрешаем всё; на реальном
# развёртывании сузить до адреса фронта.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Авторизация
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    login: str
    password: str


class LoginResponse(BaseModel):
    token: str
    name: str


@app.post("/api/login", response_model=LoginResponse)
def api_login(body: LoginRequest):
    try:
        token = auth.login(body.login, body.password)
    except auth.LoginError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e

    sess = auth.session_user(token)
    return LoginResponse(token=token, name=sess["name"])


def current_user(authorization: Optional[str] = Header(None)) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Нужен заголовок Authorization: Bearer <токен>")
    token = authorization.removeprefix("Bearer ")
    sess = auth.session_user(token)
    if sess is None:
        raise HTTPException(status_code=401, detail="Сессия истекла или недействительна")
    return sess


def optional_user(authorization: Optional[str] = Header(None)) -> dict:
    """Как current_user, но не требует входа — фронт временно без логина
    (см. историю чата), а эти ручки нужно тестировать уже сейчас. Реальный
    токен, если он есть, всё равно учитывается и попадает в actor журнала."""
    if authorization and authorization.startswith("Bearer "):
        sess = auth.session_user(authorization.removeprefix("Bearer "))
        if sess:
            return sess
    return {"login": "demo", "name": "Демо (без входа)"}


@app.post("/api/logout")
def api_logout(authorization: Optional[str] = Header(None)):
    if authorization and authorization.startswith("Bearer "):
        auth.logout(authorization.removeprefix("Bearer "))
    return {"ok": True}


# ---------------------------------------------------------------------------
# Журнал доступа ("история входов")
# ---------------------------------------------------------------------------

@app.get("/api/access-log")
def api_access_log(limit: int = 100, user=Depends(optional_user)):
    return access_log.recent(limit)


# ---------------------------------------------------------------------------
# Подключения ИИ-моделей
# ---------------------------------------------------------------------------

class AiConnectionCreate(BaseModel):
    name: str
    type: str  # external_openai | external_nvidia | local_faster_whisper
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None


@app.get("/api/ai-connections")
def api_list_connections(user=Depends(optional_user)):
    return ai_connections.list_connections()


@app.post("/api/ai-connections")
def api_create_connection(body: AiConnectionCreate, user=Depends(optional_user)):
    try:
        new_id = ai_connections.create_connection(
            name=body.name,
            type_=body.type,
            base_url=body.base_url,
            api_key=body.api_key,
            model=body.model,
            actor=user["login"],
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"id": new_id}


@app.post("/api/ai-connections/{conn_id}/test")
def api_test_connection(conn_id: int, user=Depends(optional_user)):
    try:
        return ai_connections.test_connection(conn_id, actor=user["login"])
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.post("/api/ai-connections/{conn_id}/default")
def api_set_default_connection(conn_id: int, user=Depends(optional_user)):
    try:
        ai_connections.set_default(conn_id, actor=user["login"])
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return {"ok": True}


# ---------------------------------------------------------------------------
# Загрузка аудио и распознавание
# ---------------------------------------------------------------------------

@app.post("/api/transcribe")
async def api_transcribe(file: UploadFile = File(...), user=Depends(optional_user)):
    suffix = Path(file.filename or "audio").suffix or ".mp3"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await file.read())
        tmp_path = Path(tmp.name)

    try:
        provider = ai_connections.get_default_provider()
        result = provider.transcribe(tmp_path)
    except ai_connections.NoConnectionConfigured as e:
        access_log.log(user["login"], "meeting.transcribe", "failed", message=str(e))
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001 — любая ошибка провайдера идёт в журнал и в ответ
        access_log.log(user["login"], "meeting.transcribe", "failed", message=str(e)[:500])
        raise HTTPException(status_code=502, detail=f"Распознавание не удалось: {e}") from e
    finally:
        tmp_path.unlink(missing_ok=True)

    access_log.log(user["login"], "meeting.transcribe", "success", message=file.filename)
    meeting_id = meetings.create_meeting(
        title=file.filename or "Без названия", language=result.language, transcript=result.text
    )
    return {
        "meeting_id": meeting_id,
        "language": result.language,
        "text": result.text,
        "segments": [
            {"start": s.start, "end": s.end, "text": s.text} for s in result.segments
        ],
    }


# ---------------------------------------------------------------------------
# Совещания и поручения
# ---------------------------------------------------------------------------

@app.get("/api/meetings")
def api_list_meetings(user=Depends(optional_user)):
    return meetings.list_meetings()


@app.get("/api/tasks")
def api_list_tasks(meeting_id: Optional[int] = None, user=Depends(optional_user)):
    return meetings.list_tasks(meeting_id)


@app.post("/api/meetings/{meeting_id}/extract-tasks")
def api_extract_tasks(meeting_id: int, user=Depends(optional_user)):
    meeting = meetings.get_meeting(meeting_id)
    if meeting is None:
        raise HTTPException(status_code=404, detail="Совещание не найдено")

    try:
        api_key = ai_connections.get_default_openai_key()
        extracted = tasks_extraction.extract_tasks(meeting["transcript"] or "", api_key=api_key)
    except ai_connections.NoConnectionConfigured as e:
        access_log.log(user["login"], "tasks.extract", "failed", message=str(e))
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:  # noqa: BLE001
        access_log.log(user["login"], "tasks.extract", "failed", message=str(e)[:500])
        raise HTTPException(status_code=502, detail=f"Извлечение поручений не удалось: {e}") from e

    saved = meetings.save_tasks(meeting_id, extracted)
    access_log.log(user["login"], "tasks.extract", "success", message=f"meeting {meeting_id}: {len(saved)} поручений")
    return {"tasks": saved}
