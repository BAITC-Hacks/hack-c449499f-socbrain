"""SQLite-хранилище для первого бэкенд-среза: пользователи, журнал доступа,
подключения ИИ-моделей. Одна БД-файл, без миграционного фреймворка —
для прототипа этого достаточно; таблицы создаются, если их ещё нет.
"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "socbrain.db"


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    conn = get_conn()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                login TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                password_hash TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                failed_attempts INTEGER NOT NULL DEFAULT 0,
                locked_until TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            -- "История входов" — журнал доступа. seq растёт сам (id), пропуск
            -- в номерах виден сразу — так же, как в Promt_master §07-audit.
            CREATE TABLE IF NOT EXISTS access_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                at TEXT NOT NULL DEFAULT (datetime('now')),
                actor TEXT NOT NULL,
                action TEXT NOT NULL,
                outcome TEXT NOT NULL,      -- success | failed
                ip TEXT,
                message TEXT
            );

            -- Подключения ИИ-моделей (STT/LLM) — по образцу AiConnectionService
            -- из Teams_analyz: живут в БД, редактируются из интерфейса,
            -- проверяются кнопкой "Тест", ровно одно активно как default.
            CREATE TABLE IF NOT EXISTS ai_connections (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                type TEXT NOT NULL,          -- external_openai | external_nvidia | local_faster_whisper
                base_url TEXT,
                api_key TEXT,
                model TEXT,
                is_default INTEGER NOT NULL DEFAULT 0,
                enabled INTEGER NOT NULL DEFAULT 1,
                last_check_ok INTEGER,
                last_check_message TEXT,
                last_checked_at TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            -- Совещания: пока просто файл + расшифровка, без диаризации.
            CREATE TABLE IF NOT EXISTS meetings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                language TEXT,
                transcript TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );

            -- Поручения, извлечённые LLM из расшифровки. assignee — как
            -- назвали в тексте (ФИО текстом), без привязки к учётной записи —
            -- справочника сотрудников как реальных данных ещё нет.
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                meeting_id INTEGER REFERENCES meetings(id),
                assignee TEXT NOT NULL,
                description TEXT NOT NULL,
                deadline TEXT,
                status TEXT NOT NULL DEFAULT 'in_progress',   -- in_progress | overdue | done
                created_at TEXT NOT NULL DEFAULT (datetime('now'))
            );
            """
        )
        conn.commit()
    finally:
        conn.close()
