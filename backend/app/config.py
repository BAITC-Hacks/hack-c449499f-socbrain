import ipaddress
import json
import os
import sqlite3
from pathlib import Path
from urllib.parse import urlparse

# Шаблоны подключения LLM. Все провайдеры — OpenAI-совместимый /chat/completions,
# поэтому новый = ещё одна запись здесь; код клиента не меняется.
LLM_PRESETS = {
    "nvidia": {
        "title": "NVIDIA API Catalog / NIM",
        "base_url": "https://integrate.api.nvidia.com/v1", "key_env": "NVIDIA_API_KEY",
        "model": "meta/llama-3.3-70b-instruct",
        "note": "Облако build.nvidia.com (ключ nvapi-…) — для разработки. Та же модель в контуре: "
                "контейнер NVIDIA NIM на своём GPU-сервере, адрес http://<сервер>:8000/v1.",
        "docs": "https://build.nvidia.com",
    },
    "openai": {
        "title": "OpenAI",
        "base_url": "https://api.openai.com/v1", "key_env": "OPENAI_API_KEY", "model": "gpt-4.1-mini",
        "note": "Облако — только для разработки на синтетических записях.",
        "docs": "https://platform.openai.com",
    },
    "ollama": {
        "title": "Ollama (локально)",
        "base_url": "http://ollama:11434/v1", "key_env": "OLLAMA_API_KEY", "model": "qwen2.5:3b",
        "note": "Контейнер из docker-compose: docker compose --profile local-llm up -d. Нужно от 8 ГБ RAM.",
        "docs": "https://ollama.com",
    },
    "vllm": {
        "title": "vLLM (локально)",
        "base_url": "http://vllm:8000/v1", "key_env": "VLLM_API_KEY", "model": "Qwen/Qwen2.5-7B-Instruct",
        "note": "Свой GPU-сервер в контуре; адрес — в поле «Адрес».",
        "docs": "https://docs.vllm.ai",
    },
    "none": {
        "title": "Без LLM",
        "base_url": "http://localhost/v1", "key_env": "LLM_API_KEY", "model": "",
        "note": "Поручения только по шаблону «…, ответственный X, срок Y», без саммари.",
        "docs": "",
    },
}


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    return value if value not in (None, "") else default


# Редактируемые из интерфейса разделы: поле -> (тип, переменная окружения, значение по умолчанию, варианты).
# Значение из БД (страница «Настройки») перекрывает .env; пустое значение в БД = взять из .env.
# Секреты (пароли, ключи) сюда не входят намеренно: они живут только в .env на сервере,
# интерфейс видит лишь, задан ли секрет.
SECTIONS: dict[str, dict[str, tuple]] = {
    "stt": {
        "provider": ("choice", "STT_PROVIDER", "local", ["local", "external"]),
        "language": ("choice", "WHISPER_LANGUAGE", "", ["", "ru", "kk"]),
        "prompt": ("text", "WHISPER_PROMPT", "Совещание. Поручения, ответственные, сроки.", None),
    },
    "diarization": {
        "num_speakers": ("int", "NUM_SPEAKERS", "0", None),
        "threshold": ("float", "DIARIZATION_THRESHOLD", "0.5", None),
        "min_talk_seconds": ("float", "DIARIZATION_MIN_TALK", "3", None),
    },
    "llm": {
        "provider": ("choice", "LLM_PROVIDER", "ollama", list(LLM_PRESETS)),
        "model": ("text", "LLM_MODEL", "", None),
        "base_url": ("text", "LLM_BASE_URL", "", None),
        "timeout": ("int", "LLM_TIMEOUT", "300", None),
    },
    "processing": {
        "remind_days_before": ("int", "REMIND_DAYS_BEFORE", "2", None),
        "audio_retention_days": ("int", "AUDIO_RETENTION_DAYS", "30", None),
    },
    "mail": {
        "host": ("text", "SMTP_HOST", "", None),
        "port": ("int", "SMTP_PORT", "587", None),
        "security": ("choice", "SMTP_SECURITY", "starttls", ["starttls", "ssl", "none"]),
        "username": ("text", "SMTP_USERNAME", "", None),
        "sender": ("text", "SMTP_FROM", "", None),
        "reminders_enabled": ("bool", "MAIL_REMINDERS", "false", None),
    },
    "appearance": {
        "theme": ("choice", "UI_THEME", "system", ["system", "light", "dark"]),
        "density": ("choice", "UI_DENSITY", "normal", ["normal", "compact"]),
        "font_scale": ("choice", "UI_FONT_SCALE", "100", ["100", "115", "130"]),
        "high_contrast": ("bool", "UI_HIGH_CONTRAST", "false", None),
        "reduce_motion": ("bool", "UI_REDUCE_MOTION", "false", None),
        "org_name": ("text", "ORG_NAME", "", None),
    },
    "integrations": {
        "zoom_enabled": ("bool", "ZOOM_ENABLED", "false", None),
        "zoom_account_id": ("text", "ZOOM_ACCOUNT_ID", "", None),
        "zoom_client_id": ("text", "ZOOM_CLIENT_ID", "", None),
        "teams_enabled": ("bool", "TEAMS_ENABLED", "false", None),
        "teams_tenant_id": ("text", "TEAMS_TENANT_ID", "", None),
        "teams_client_id": ("text", "TEAMS_CLIENT_ID", "", None),
        "meet_enabled": ("bool", "MEET_ENABLED", "false", None),
        "meet_service_account": ("text", "MEET_SERVICE_ACCOUNT", "", None),
        "sed_enabled": ("bool", "SED_ENABLED", "false", None),
        "sed_url": ("text", "SED_URL", "", None),
    },
}

# Секреты по разделам. Задаются в .env или в интерфейсе (app/vault.py: шифрование, привязка к хосту);
# значения интерфейсу не отдаются никогда.
SECRETS = {
    "mail": ["SMTP_PASSWORD"],
    "integrations": ["ZOOM_CLIENT_SECRET", "TEAMS_CLIENT_SECRET", "MEET_KEY_FILE", "SED_API_KEY"],
    "llm": sorted({p["key_env"] for p in LLM_PRESETS.values()}),
}


def coerce(kind: str, raw, choices=None):
    """Привести значение к типу поля; ValueError — если нельзя."""
    if kind == "bool":
        return raw if isinstance(raw, bool) else str(raw).lower() in ("1", "true", "yes", "on")
    if kind == "int":
        return int(raw)
    if kind == "float":
        return float(raw)
    value = str(raw).strip()
    if kind == "choice" and value not in choices:
        raise ValueError(f"допустимо: {', '.join(c or '(пусто)' for c in choices)}")
    return value


def load_overrides(db_path: Path) -> dict:
    """Настройки, сохранённые из интерфейса (таблица app_settings)."""
    if not db_path.exists():
        return {}
    try:
        conn = sqlite3.connect(db_path, timeout=5)
        try:
            rows = conn.execute("SELECT section, value FROM app_settings").fetchall()
        finally:
            conn.close()
    except sqlite3.Error:
        return {}
    return {section: json.loads(value) for section, value in rows}


def is_external_url(url: str) -> bool:
    """Признак вычисляется по адресу, а не задаётся переключателем: администратор ошибётся, адрес не соврёт."""
    host = urlparse(url).hostname or ""
    if "." not in host or host == "localhost" or host.endswith((".local", ".internal", ".lan")):
        return False
    try:
        return not ipaddress.ip_address(host).is_private
    except ValueError:
        return True


class Settings:
    """Действующая конфигурация: .env + перекрытия из интерфейса. reload() перечитывает БД."""

    def __init__(self) -> None:
        self.data_dir = Path(_env("DATA_DIR", "/data"))
        self.models_dir = Path(_env("MODELS_DIR", "/models"))
        # Модель распознавания встраивается в образ при сборке — из интерфейса не меняется.
        self.whisper_model = _env("WHISPER_MODEL", "small")
        self.whisper_compute = _env("WHISPER_COMPUTE", "int8")
        self.cpu_threads = int(_env("CPU_THREADS", "4"))
        self.llm_temperature = float(os.environ["LLM_TEMPERATURE"]) if os.getenv("LLM_TEMPERATURE") else None
        self.values: dict[str, dict] = {}
        self.reload()

    def reload(self, overrides: dict | None = None) -> None:
        overrides = load_overrides(self.db_path) if overrides is None else overrides
        values: dict[str, dict] = {}
        for section, fields in SECTIONS.items():
            saved = overrides.get(section, {})
            values[section] = {}
            for name, (kind, env, default, choices) in fields.items():
                raw = saved.get(name)
                if raw in (None, ""):
                    raw = _env(env, default)
                try:
                    values[section][name] = coerce(kind, raw, choices)
                except ValueError:
                    values[section][name] = coerce(kind, default, choices)
        self.values = values

        stt, diar, llm = values["stt"], values["diarization"], values["llm"]
        self.stt_provider = stt["provider"]
        self.whisper_language = stt["language"] or None  # None = язык по фрагментам
        self.whisper_prompt = stt["prompt"]
        self.num_speakers = diar["num_speakers"]
        self.diarization_threshold = diar["threshold"]
        self.diarization_min_talk = diar["min_talk_seconds"]

        # LLM: openai | nvidia | ollama | vllm | none. Все — через OpenAI-совместимый API.
        self.llm_provider = llm["provider"]
        preset = LLM_PRESETS.get(self.llm_provider, LLM_PRESETS["ollama"])
        self.llm_base_url = (llm["base_url"] or preset["base_url"]).rstrip("/")
        self.llm_api_key_env = _env("LLM_API_KEY_ENV", preset["key_env"])
        # Ключ из интерфейса (зашифрован, привязан к хосту) или из .env
        self.llm_api_key = self.secret(self.llm_api_key_env, self.llm_base_url)
        self.llm_model = llm["model"] or preset["model"]
        self.llm_timeout = float(llm["timeout"])
        # Облачным адресам нужен ключ; NIM/vLLM в своём контуре обычно без него.
        self.llm_requires_key = is_external_url(self.llm_base_url) and self.llm_provider != "none"

        self.remind_days_before = values["processing"]["remind_days_before"]
        self.audio_retention_days = values["processing"]["audio_retention_days"]

    def secret(self, name: str, host: str | None = None) -> str:
        from . import vault
        return vault.get_secret(self.data_dir, name, host)

    def secret_host(self, name: str) -> str | None:
        """Куда будет отправляться секрет — к этому хосту он и привязывается при сохранении."""
        if name == "SMTP_PASSWORD":
            return self.values["mail"]["host"] or None
        if name == self.llm_api_key_env:
            return self.llm_base_url
        owner = next((p for p in LLM_PRESETS.values() if p["key_env"] == name), None)
        return owner["base_url"] if owner else None

    @property
    def llm_external(self) -> bool:
        """Уходит ли текст за пределы контура (облачный API)."""
        return is_external_url(self.llm_base_url)

    @property
    def db_path(self) -> Path:
        return self.data_dir / "protocol.db"

    @property
    def upload_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def work_dir(self) -> Path:
        return self.data_dir / "work"


settings = Settings()
