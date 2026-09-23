"""Подключения ИИ-моделей — по образцу AiConnectionService из Teams_analyz:
живут в БД, добавляются/проверяются из интерфейса, ровно одна помечена
default и используется пайплайном. Так "ввод новой модели" сразу
"работает" — не нужно лезть в .env и перезапускать процесс.
"""

from datetime import datetime, timezone

from . import access_log
from .db import get_conn
from .stt.base import STTProvider

VALID_TYPES = {"external_openai", "external_nvidia", "local_faster_whisper"}


def create_connection(
    name: str, type_: str, base_url: str | None, api_key: str | None, model: str | None, actor: str
) -> int:
    if type_ not in VALID_TYPES:
        raise ValueError(f"Неизвестный тип подключения: {type_!r} (ожидается один из {VALID_TYPES})")

    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO ai_connections (name, type, base_url, api_key, model) VALUES (?, ?, ?, ?, ?)",
            (name, type_, base_url, api_key, model),
        )
        conn.commit()
        new_id = cur.lastrowid
    finally:
        conn.close()

    access_log.log(actor, "ai_connection.created", "success", message=f"{name} ({type_})")
    return new_id


def list_connections() -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT id, name, type, base_url, model, is_default, enabled, "
            "last_check_ok, last_check_message, last_checked_at, created_at "
            "FROM ai_connections ORDER BY is_default DESC, id"
        ).fetchall()
        # api_key намеренно не выбран — секрет обратно не отдаётся, как в
        # Promt_master §4.1 "Поле секрета": можно только заменить.
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _get(conn_id: int) -> dict:
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM ai_connections WHERE id = ?", (conn_id,)).fetchone()
        if row is None:
            raise ValueError(f"Подключение {conn_id} не найдено")
        return dict(row)
    finally:
        conn.close()


def set_default(conn_id: int, actor: str) -> None:
    _get(conn_id)  # проверить, что существует
    conn = get_conn()
    try:
        conn.execute("UPDATE ai_connections SET is_default = 0")
        conn.execute("UPDATE ai_connections SET is_default = 1 WHERE id = ?", (conn_id,))
        conn.commit()
    finally:
        conn.close()
    access_log.log(actor, "ai_connection.set_default", "success", message=str(conn_id))


def build_provider(row: dict) -> STTProvider:
    """Собирает STTProvider из строки БД — ровно та точка, где 'ввод модели'
    превращается в 'модель работает'.
    """
    if row["type"] == "external_openai":
        from .stt.external_openai import OpenAIWhisperProvider

        return OpenAIWhisperProvider(api_key=row["api_key"] or "", model=row["model"] or "whisper-1")

    if row["type"] == "external_nvidia":
        from .stt.external_nvidia_riva import NvidiaRivaProvider

        return NvidiaRivaProvider(api_key=row["api_key"] or "")

    if row["type"] == "local_faster_whisper":
        from .stt.local_faster_whisper import FasterWhisperProvider

        return FasterWhisperProvider(model_size=row["model"] or "large-v3")

    raise ValueError(f"Неизвестный тип подключения: {row['type']!r}")


def test_connection(conn_id: int, actor: str) -> dict:
    """Пробует собрать провайдера с текущими настройками — как минимум
    ловит опечатку в ключе/адресе до того, как ей воспользуется реальная
    расшифровка. Полноценный сетевой запрос (как ListModelsAsync у
    Teams_analyz) — следующий шаг, когда будет что вызывать без траты
    платных токенов на каждый клик "Тест".
    """
    row = _get(conn_id)
    ok = True
    message = "Подключение собрано успешно"
    try:
        build_provider(row)
    except Exception as e:  # noqa: BLE001 — здесь любая ошибка это "тест не прошёл"
        ok = False
        message = str(e)[:500]

    conn = get_conn()
    try:
        conn.execute(
            "UPDATE ai_connections SET last_check_ok = ?, last_check_message = ?, last_checked_at = ? "
            "WHERE id = ?",
            (1 if ok else 0, message, datetime.now(timezone.utc).isoformat(), conn_id),
        )
        conn.commit()
    finally:
        conn.close()

    access_log.log(actor, "ai_connection.tested", "success" if ok else "failed", message=message)
    return {"ok": ok, "message": message}


class NoConnectionConfigured(Exception):
    pass


def _get_default_row() -> dict | None:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM ai_connections WHERE enabled = 1 ORDER BY is_default DESC, id LIMIT 1"
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def get_default_openai_key() -> str:
    """Ключ для извлечения поручений (LLM) — переиспользует тот же ключ,
    что настроен для STT (external_openai), раз это один и тот же
    OpenAI-аккаунт. Тот же принцип: без настроенного подключения —
    явная ошибка, не .env.
    """
    row = _get_default_row()
    if row is None or row["type"] != "external_openai" or not row["api_key"]:
        raise NoConnectionConfigured(
            "Для извлечения поручений нужен подключённый OpenAI-ключ. "
            "Добавь подключение типа external_openai в Настройки → "
            "Распознавание речи и ИИ и сделай его подключением по умолчанию."
        )
    return row["api_key"]


def get_default_provider() -> STTProvider:
    """Для API продукта — строго то, что настроено через интерфейс.

    Без тихого фолбэка на .env: если пользователь ничего не добавил в
    "Настройки → Распознавание речи и ИИ", он должен увидеть явную
    просьбу настроить модель, а не незаметно пользоваться чужим
    (разработческим) ключом из .env — на нём был бы чужой счёт и чужая
    квота, о которой пользователь даже не подозревает.
    """
    row = _get_default_row()
    if row is None:
        raise NoConnectionConfigured(
            "Ни одна модель распознавания не настроена. Добавь подключение "
            "в Настройки → Распознавание речи и ИИ."
        )
    return build_provider(row)


def get_default_provider_or_env_fallback() -> STTProvider:
    """Только для локальных dev-инструментов (см. app/transcribe.py) —
    там .env-фолбэк уместен, это личный CLI разработчика, не продуктовый API.
    """
    row = _get_default_row()
    if row is None:
        from .stt import get_provider

        return get_provider()
    return build_provider(row)
