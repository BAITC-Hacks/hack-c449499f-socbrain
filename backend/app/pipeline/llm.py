"""Клиент LLM через OpenAI-совместимый /chat/completions.

Один код для облака (OpenAI, NVIDIA NIM) и закрытого контура (vLLM, Ollama) —
провайдер меняется настройкой LLM_PROVIDER, без правки кода.
"""
import json
import logging
import re

import httpx

from ..config import settings

log = logging.getLogger(__name__)


class LLMError(RuntimeError):
    pass


def _strict(schema: dict) -> dict:
    """Строгий режим OpenAI требует additionalProperties=false у каждого объекта."""
    if isinstance(schema, dict):
        schema = {k: _strict(v) for k, v in schema.items()}
        if schema.get("type") == "object":
            schema["additionalProperties"] = False
    elif isinstance(schema, list):
        schema = [_strict(v) for v in schema]
    return schema


def _parse(content: str) -> dict:
    """Достаёт JSON из ответа: модели без строгого режима оборачивают его в ```json и <think>."""
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", content, flags=re.DOTALL)
    if fenced:
        content = fenced.group(1)
    start, end = content.find("{"), content.rfind("}")
    if start < 0 or end < start:
        raise json.JSONDecodeError("no JSON object in response", content, 0)
    return json.loads(content[start:end + 1])


def _post(payload: dict) -> str:
    headers = {"Authorization": f"Bearer {settings.llm_api_key}"} if settings.llm_api_key else {}
    response = httpx.post(f"{settings.llm_base_url}/chat/completions", json=payload, headers=headers,
                          timeout=settings.llm_timeout)
    if response.status_code >= 400:
        raise httpx.HTTPStatusError(response.text[:500], request=response.request, response=response)
    return response.json()["choices"][0]["message"]["content"]


def chat_json(system: str, user: str, schema: dict, name: str = "result") -> dict:
    payload = {
        "model": settings.llm_model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "response_format": {"type": "json_schema",
                            "json_schema": {"name": name, "schema": _strict(schema), "strict": True}},
    }
    if settings.llm_temperature is not None:
        payload["temperature"] = settings.llm_temperature
    try:
        try:
            return _parse(_post(payload))
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 400:
                raise
            # провайдер не поддерживает json_schema — просим JSON по схеме в тексте инструкции
            log.warning("json_schema rejected by provider, retrying with schema in prompt: %s", exc)
            payload["response_format"] = {"type": "json_object"}
            payload["messages"][0]["content"] = (
                f"{system}\n\nОтветь ТОЛЬКО JSON-объектом по этой JSON-схеме:\n"
                f"{json.dumps(schema, ensure_ascii=False)}")
            try:
                return _parse(_post(payload))
            except httpx.HTTPStatusError as exc2:
                if exc2.response.status_code != 400:
                    raise
                del payload["response_format"]
                return _parse(_post(payload))
    except (httpx.HTTPError, KeyError, IndexError, json.JSONDecodeError) as exc:
        raise LLMError(f"{type(exc).__name__}: {exc}") from exc


def check() -> dict:
    """Проверка подключения для страницы настроек: доступность, ключ, наличие модели, пробный запрос.

    Пробный запрос — короткий синтетический текст, не данные совещаний.
    """
    result = {"provider": settings.llm_provider, "base_url": settings.llm_base_url, "model": settings.llm_model,
              "external": settings.llm_external, "key_env": settings.llm_api_key_env,
              "key_set": bool(settings.llm_api_key), "reachable": False, "model_listed": None,
              "models": [], "structured_ok": False, "error": None}
    if settings.llm_provider == "none":
        result["error"] = "LLM отключена (LLM_PROVIDER=none)"
        return result
    if settings.llm_requires_key and not settings.llm_api_key:
        result["error"] = f"Не задан ключ: впишите {settings.llm_api_key_env}=… в backend/.env и перезапустите worker"
        return result
    headers = {"Authorization": f"Bearer {settings.llm_api_key}"} if settings.llm_api_key else {}
    try:
        response = httpx.get(f"{settings.llm_base_url}/models", headers=headers, timeout=20)
        result["reachable"] = response.status_code == 200
        if response.status_code in (401, 403):
            result["error"] = "Ключ отклонён провайдером (401/403)"
            return result
        ids = sorted(m.get("id", "") for m in response.json().get("data", []))
        result["models"] = ids[:300]
        result["model_listed"] = settings.llm_model in ids if ids else None
    except (httpx.HTTPError, ValueError) as exc:
        result["error"] = f"Сервер недоступен: {exc}"
        return result
    try:
        answer = chat_json("Ответь по схеме.", "Поручение: подготовить отчёт, ответственный Иванов, срок пятница.",
                           {"type": "object", "properties": {"assignee": {"type": "string"}},
                            "required": ["assignee"]}, "check")
        result["structured_ok"] = bool(answer.get("assignee"))
    except LLMError as exc:
        result["error"] = f"Пробный запрос не прошёл: {exc}"
    return result


def available() -> bool:
    if settings.llm_provider == "none":
        return False
    if settings.llm_requires_key and not settings.llm_api_key:
        log.warning("LLM provider %s has no API key (%s)", settings.llm_provider, settings.llm_api_key_env)
        return False
    headers = {"Authorization": f"Bearer {settings.llm_api_key}"} if settings.llm_api_key else {}
    try:
        return httpx.get(f"{settings.llm_base_url}/models", headers=headers, timeout=15).status_code == 200
    except httpx.HTTPError as exc:
        log.warning("LLM %s unreachable: %s", settings.llm_base_url, exc)
        return False
