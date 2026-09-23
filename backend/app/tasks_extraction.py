"""Извлечение поручений из текста расшифровки через LLM (OpenAI chat
completions). Использует тот же ключ, что настроен для STT в "Настройки →
Распознавание речи и ИИ" — тот же принцип "без тихого фолбэка на .env",
что и в app/ai_connections.py: без настроенного подключения — явная ошибка.
"""

import json

from openai import OpenAI

EXTRACT_SYSTEM_PROMPT = """Ты помощник, который читает расшифровку совещания и \
выделяет из неё поручения. Поручение — это когда кто-то явно поручает \
конкретному человеку что-то сделать, обычно со сроком.

Верни строго JSON-массив объектов с полями:
- "assignee": ФИО ответственного, как оно звучит в тексте (строка)
- "task": суть поручения, кратко и по-русски (строка)
- "deadline": срок, как он назван в тексте (строка, например "15 октября", \
"до пятницы", "2 недели"); если срок не назван — null

Если поручений нет — верни пустой массив []. Не выдумывай поручения, которых \
нет в тексте. Ответ — только JSON, без пояснений и без markdown-обёртки."""


def extract_tasks(transcript_text: str, api_key: str, model: str = "gpt-4o-mini") -> list[dict]:
    if not transcript_text.strip():
        return []

    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": EXTRACT_SYSTEM_PROMPT},
            {"role": "user", "content": transcript_text},
        ],
        response_format={"type": "json_object"},
        temperature=0,
    )

    raw = response.choices[0].message.content or "{}"
    parsed = json.loads(raw)

    # Модель иногда оборачивает массив в {"tasks": [...]}, несмотря на промпт —
    # подстраховываемся вместо того, чтобы падать на разборе.
    if isinstance(parsed, list):
        return parsed
    if isinstance(parsed, dict):
        for value in parsed.values():
            if isinstance(value, list):
                return value
    return []
