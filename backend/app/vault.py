"""Секреты, введённые в интерфейсе: ключи LLM, пароль SMTP, секреты интеграций.

- Хранятся в БД зашифрованными (Fernet). Мастер-ключ — SECRETS_KEY из .env; если не задан,
  создаётся файл <DATA_DIR>/.secrets_key с правами 600. Дамп базы без него бесполезен.
- Наружу не отдаются никогда: API показывает только «задан, …ab12» и источник.
- Ключ привязан к хосту, для которого его сохранили. Сменили адрес LLM на чужой сервер —
  сохранённый ключ туда не уйдёт (иначе любой в сети мог бы увести ключ, поменяв адрес).
- Значение из интерфейса главнее .env; .env — запасной вариант.

Модуль не импортирует db/config: config вызывает его при своей инициализации.
"""
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from cryptography.fernet import Fernet, InvalidToken

SCHEMA = """
CREATE TABLE IF NOT EXISTS app_secrets (
    name       TEXT PRIMARY KEY,   -- имя как в .env: NVIDIA_API_KEY, SMTP_PASSWORD, ...
    value_enc  TEXT NOT NULL,      -- Fernet-токен
    hint       TEXT NOT NULL,      -- последние 4 символа, чтобы узнать ключ, не раскрывая его
    bound_host TEXT,               -- ключ отдаётся только для этого хоста; NULL — без привязки
    updated_at TEXT NOT NULL
)"""


def host_of(url_or_host: str | None) -> str | None:
    if not url_or_host:
        return None
    return (urlparse(url_or_host).hostname if "://" in url_or_host else url_or_host).lower()


def _fernet(data_dir: Path) -> Fernet:
    key = os.getenv("SECRETS_KEY")
    if not key:
        path = data_dir / ".secrets_key"
        if not path.exists():
            data_dir.mkdir(parents=True, exist_ok=True)
            path.write_bytes(Fernet.generate_key())
            path.chmod(0o600)
        key = path.read_bytes().decode()
    return Fernet(key)


def _connect(data_dir: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(data_dir / "protocol.db", timeout=10, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute(SCHEMA)
    return conn


def set_secret(data_dir: Path, name: str, value: str, bound_host: str | None) -> None:
    token = _fernet(data_dir).encrypt(value.encode()).decode()
    conn = _connect(data_dir)
    try:
        conn.execute(
            "INSERT INTO app_secrets (name, value_enc, hint, bound_host, updated_at) VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT (name) DO UPDATE SET value_enc = excluded.value_enc, hint = excluded.hint,"
            " bound_host = excluded.bound_host, updated_at = excluded.updated_at",
            (name, token, value[-4:], host_of(bound_host), datetime.now().isoformat(timespec="seconds")))
    finally:
        conn.close()


def clear_secret(data_dir: Path, name: str) -> None:
    conn = _connect(data_dir)
    try:
        conn.execute("DELETE FROM app_secrets WHERE name = ?", (name,))
    finally:
        conn.close()


def _row(data_dir: Path, name: str) -> sqlite3.Row | None:
    if not (data_dir / "protocol.db").exists():
        return None
    try:
        conn = _connect(data_dir)
        try:
            return conn.execute("SELECT * FROM app_secrets WHERE name = ?", (name,)).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return None


def get_secret(data_dir: Path, name: str, host: str | None = None) -> str:
    """Значение секрета для запроса к host: из интерфейса (если привязка совпадает), иначе из .env."""
    row = _row(data_dir, name)
    if row and (row["bound_host"] is None or row["bound_host"] == host_of(host)):
        try:
            return _fernet(data_dir).decrypt(row["value_enc"].encode()).decode()
        except (InvalidToken, ValueError):
            pass  # сменили мастер-ключ — сохранённое значение нечитаемо, берём .env
    return os.getenv(name, "")


def status(data_dir: Path, name: str, host: str | None = None) -> dict:
    """Что показать в интерфейсе — без значения."""
    row = _row(data_dir, name)
    if row:
        usable = row["bound_host"] is None or host is None or row["bound_host"] == host_of(host)
        return {"set": True, "source": "интерфейс", "hint": f"…{row['hint']}", "bound_host": row["bound_host"],
                "usable": usable, "updated_at": row["updated_at"]}
    if os.getenv(name):
        return {"set": True, "source": ".env", "hint": f"…{os.getenv(name)[-4:]}", "bound_host": None,
                "usable": True, "updated_at": None}
    return {"set": False, "source": None, "hint": "", "bound_host": None, "usable": False, "updated_at": None}
