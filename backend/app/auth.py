"""Логин с блокировкой после подбора и логированием каждой попытки —
по образцу auth.go из Analyz-zapis (bcrypt, blokировка на 15 минут после
5 неудач) и Login.cshtml.cs из Teams_analyz (один и тот же текст ошибки
для "нет такого логина" и "неверный пароль" — иначе по разнице ответов
можно перебрать список существующих учёток).
"""

import secrets
import time
from datetime import datetime, timedelta, timezone

import bcrypt

from . import access_log
from .db import get_conn

MAX_ATTEMPTS = 5
LOCK_MINUTES = 15
SESSION_TTL_HOURS = 12

# Сессии — в памяти процесса, как в Analyz-zapis: перезапуск бэкенда
# разлогинивает всех, это приемлемо для прототипа и не требует таблицы,
# которую надо чистить от протухшего.
_sessions: dict[str, dict] = {}


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode("utf-8")


def create_user(login: str, name: str, password: str) -> int:
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO users (login, name, password_hash) VALUES (?, ?, ?)",
            (login, name, hash_password(password)),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _get_user(login: str) -> dict | None:
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM users WHERE login = ?", (login,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def _note_failed_attempt(user_id: int, attempts: int) -> None:
    conn = get_conn()
    try:
        locked_until = None
        if attempts >= MAX_ATTEMPTS:
            locked_until = (datetime.now(timezone.utc) + timedelta(minutes=LOCK_MINUTES)).isoformat()
        conn.execute(
            "UPDATE users SET failed_attempts = ?, locked_until = ? WHERE id = ?",
            (attempts, locked_until, user_id),
        )
        conn.commit()
    finally:
        conn.close()


def _reset_attempts(user_id: int) -> None:
    conn = get_conn()
    try:
        conn.execute(
            "UPDATE users SET failed_attempts = 0, locked_until = NULL WHERE id = ?", (user_id,)
        )
        conn.commit()
    finally:
        conn.close()


class LoginError(Exception):
    pass


def login(login_name: str, password: str, ip: str | None = None) -> str:
    """Возвращает токен сессии при успехе, иначе бросает LoginError.
    Каждая попытка — успешная или нет — пишется в access_log.
    """
    user = _get_user(login_name)

    if user is None:
        # тратим время как на настоящую bcrypt-проверку, чтобы отсутствие
        # пользователя не выдавало себя мгновенным ответом (см. auth.go)
        bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12))
        access_log.log(login_name, "login", "failed", ip, "неверный логин или пароль")
        raise LoginError("Неверный логин или пароль")

    if not user["is_active"]:
        access_log.log(login_name, "login", "failed", ip, "учётная запись отключена")
        raise LoginError("Неверный логин или пароль")

    if user["locked_until"]:
        locked_until = datetime.fromisoformat(user["locked_until"])
        if datetime.now(timezone.utc) < locked_until:
            access_log.log(login_name, "login", "failed", ip, "вход заблокирован после подбора")
            raise LoginError("Вход временно заблокирован после неудачных попыток")

    if not bcrypt.checkpw(password.encode("utf-8"), user["password_hash"].encode("utf-8")):
        _note_failed_attempt(user["id"], user["failed_attempts"] + 1)
        access_log.log(login_name, "login", "failed", ip, "неверный логин или пароль")
        raise LoginError("Неверный логин или пароль")

    _reset_attempts(user["id"])
    access_log.log(login_name, "login", "success", ip, None)

    token = secrets.token_urlsafe(32)
    _sessions[token] = {
        "user_id": user["id"],
        "login": user["login"],
        "name": user["name"],
        "expires": time.time() + SESSION_TTL_HOURS * 3600,
    }
    return token


def session_user(token: str) -> dict | None:
    sess = _sessions.get(token)
    if sess is None or time.time() > sess["expires"]:
        _sessions.pop(token, None)
        return None
    return sess


def logout(token: str) -> None:
    _sessions.pop(token, None)
