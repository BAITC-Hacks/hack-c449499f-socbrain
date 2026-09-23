import ipaddress
import os
from pathlib import Path
from urllib.parse import urlparse

LLM_PRESETS = {
    "openai": {"base_url": "https://api.openai.com/v1", "key_env": "OPENAI_API_KEY", "model": "gpt-4.1-mini"},
    "nvidia": {"base_url": "https://integrate.api.nvidia.com/v1", "key_env": "NVIDIA_API_KEY",
               "model": "meta/llama-3.3-70b-instruct"},
    "ollama": {"base_url": "http://ollama:11434/v1", "key_env": "OLLAMA_API_KEY", "model": "qwen2.5:3b"},
    "vllm": {"base_url": "http://vllm:8000/v1", "key_env": "VLLM_API_KEY", "model": "Qwen/Qwen2.5-7B-Instruct"},
    "none": {"base_url": "http://localhost/v1", "key_env": "LLM_API_KEY", "model": ""},
}


def _env(name: str, default: str) -> str:
    value = os.getenv(name)
    return value if value not in (None, "") else default


class Settings:
    data_dir = Path(_env("DATA_DIR", "/data"))
    models_dir = Path(_env("MODELS_DIR", "/models"))

    whisper_model = _env("WHISPER_MODEL", "small")
    whisper_compute = _env("WHISPER_COMPUTE", "int8")
    whisper_language = os.getenv("WHISPER_LANGUAGE") or None  # None = автоопределение
    whisper_prompt = _env("WHISPER_PROMPT", "Совещание. Поручения, ответственные, сроки.")
    cpu_threads = int(_env("CPU_THREADS", "4"))

    num_speakers = int(_env("NUM_SPEAKERS", "0"))
    diarization_threshold = float(_env("DIARIZATION_THRESHOLD", "0.5"))

    # LLM: openai | nvidia | ollama | vllm | none. Все — через OpenAI-совместимый API.
    llm_provider = _env("LLM_PROVIDER", "ollama").lower()
    llm_base_url = _env("LLM_BASE_URL", LLM_PRESETS.get(llm_provider, LLM_PRESETS["ollama"])["base_url"]).rstrip("/")
    llm_api_key_env = _env("LLM_API_KEY_ENV", LLM_PRESETS.get(llm_provider, {}).get("key_env", "LLM_API_KEY"))
    llm_api_key = os.getenv(llm_api_key_env, "")
    llm_requires_key = llm_provider in ("openai", "nvidia")
    llm_model = _env("LLM_MODEL", LLM_PRESETS.get(llm_provider, LLM_PRESETS["ollama"])["model"])
    llm_temperature = float(os.environ["LLM_TEMPERATURE"]) if os.getenv("LLM_TEMPERATURE") else None
    llm_timeout = float(_env("LLM_TIMEOUT", "900"))

    @property
    def llm_external(self) -> bool:
        """Уходит ли текст за пределы контура (облачный API)."""
        host = urlparse(self.llm_base_url).hostname or ""
        if "." not in host or host == "localhost" or host.endswith((".local", ".internal", ".lan")):
            return False
        try:
            return not ipaddress.ip_address(host).is_private
        except ValueError:
            return True

    remind_days_before = int(_env("REMIND_DAYS_BEFORE", "2"))

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
