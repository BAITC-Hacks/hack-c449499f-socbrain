"""Анализ транскрипта: кто есть кто, поручения (что / кто / срок), саммари."""
import difflib
import json
import logging
import re
from datetime import date

from . import llm
from .align import format_transcript
from .dates import parse_deadline

log = logging.getLogger(__name__)

CHUNK_CHARS = 9000  # ~3 тыс. токенов: помещается в контекст 8k вместе с инструкцией и ответом

PRIORITIES = ["high", "medium", "low"]
CATEGORIES = ["производство", "финансы", "инвестиции", "закупки", "юридическое", "безопасность",
              "персонал", "подрядчики", "отчётность", "прочее"]

SPEAKERS_SYSTEM = """Ты анализируешь транскрипт совещания в казахстанской компании (русский, казахский или смешанная речь).
Говорящие обозначены метками SPEAKER_XX (автоматическая диаризация, возможны ошибки).
Определи для каждой метки имя (обычно имя и отчество) и должность, если их можно понять из текста.
Подсказки: к человеку обращаются по имени перед тем, как он отвечает ("Тимур Болатович, что у вас?" —
следующая реплика, скорее всего, его); должности звучат при представлении; председатель ведёт совещание и раздаёт поручения.
Не выдумывай: если имя неизвестно — оставь пустую строку."""

SPEAKERS_SCHEMA = {
    "type": "object",
    "properties": {"speakers": {"type": "array", "items": {
        "type": "object",
        "properties": {"label": {"type": "string"}, "name": {"type": "string"}, "role": {"type": "string"}},
        "required": ["label", "name", "role"]}}},
    "required": ["speakers"],
}

TASKS_SYSTEM = f"""Ты — секретарь совещания. Извлеки из фрагмента транскрипта ВСЕ поручения.
Поручение — конкретное действие, которое кто-то обязан выполнить. Бывают явные ("Фиксируем поручения. Первое: ...")
и неявные ("до пятницы разберитесь с подрядчиком и доложите", "пусть Ерлан подготовит претензию").
Правила:
- assignee — КОМУ поручено (обычно к нему обращаются по имени перед поручением), а не тот, кто поручает.
  Если ответственный — подразделение или человек, которого нет на совещании, укажи как сказано ("юридический департамент", "Ерлан").
- issuer — метка SPEAKER_XX того, кто дал поручение.
- description — суть поручения кратко, в инфинитиве, по-русски ("Провести аудит датчиков утечки на 11 площадках").
- deadline_text — срок ДОСЛОВНО как сказано ("до пятницы", "к пятнадцатому октября", "на этой неделе"); нет срока — пустая строка.
- quote — короткая цитата из транскрипта, где дано поручение.
- priority — {"/".join(PRIORITIES)}: high — безопасность, срыв сроков, прямые указания руководителя "лично доложить".
- category — одна из: {", ".join(CATEGORIES)}.
- Если в конце совещания поручения повторяются в итоге — НЕ дублируй, но уточни срок, если в итоге он конкретнее.
- Вопросы, предложения и мнения без согласованного действия — не поручения. Не выдумывай."""

TASKS_SCHEMA = {
    "type": "object",
    "properties": {"tasks": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "description": {"type": "string"}, "assignee": {"type": "string"}, "issuer": {"type": "string"},
            "deadline_text": {"type": "string"}, "quote": {"type": "string"},
            "priority": {"type": "string", "enum": PRIORITIES}, "category": {"type": "string", "enum": CATEGORIES},
        },
        "required": ["description", "assignee", "issuer", "deadline_text", "quote", "priority", "category"]}}},
    "required": ["tasks"],
}

SUMMARY_SYSTEM = """Составь краткое деловое саммари совещания на русском языке (даже если говорили по-казахски).
overview — 2–3 предложения: о чём совещание и главный итог.
topics — вопросы повестки; для каждого 2–4 ключевых факта (цифры, проблемы, риски).
decisions — принятые решения (не повторяй поручения дословно). Не выдумывай фактов, которых нет в транскрипте."""

SUMMARY_SCHEMA = {
    "type": "object",
    "properties": {
        "overview": {"type": "string"},
        "topics": {"type": "array", "items": {
            "type": "object",
            "properties": {"title": {"type": "string"}, "points": {"type": "array", "items": {"type": "string"}}},
            "required": ["title", "points"]}},
        "decisions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["overview", "topics", "decisions"],
}


def _chunks(lines: list[str]) -> list[str]:
    chunks, current, size = [], [], 0
    for line in lines:
        if current and size + len(line) > CHUNK_CHARS:
            chunks.append("\n".join(current))
            current, size = current[-3:], sum(len(x) for x in current[-3:])  # небольшое перекрытие контекста
        current.append(line)
        size += len(line)
    if current:
        chunks.append("\n".join(current))
    return chunks


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", (text or "").lower())).strip()


def _similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, _normalize(a), _normalize(b)).ratio()


def match_speaker(assignee: str, speakers: list[dict]) -> str | None:
    """Сопоставляет ответственного с участником совещания (имена из ASR могут быть искажены)."""
    if not assignee:
        return None
    best, best_score = None, 0.0
    for speaker in speakers:
        if not speaker.get("name"):
            continue
        score = _similar(assignee, speaker["name"])
        first_a, first_s = _normalize(assignee).split()[:1], _normalize(speaker["name"]).split()[:1]
        if first_a and first_a == first_s:
            score = max(score, 0.8)
        if score > best_score:
            best, best_score = speaker["label"], score
    return best if best_score >= 0.75 else None


def _dedupe(tasks: list[dict]) -> list[dict]:
    result: list[dict] = []
    for task in tasks:
        duplicate = next((t for t in result
                          if _similar(t["assignee"], task["assignee"]) > 0.8
                          and _similar(t["description"], task["description"]) > 0.6), None)
        if duplicate is None:
            result.append(task)
        elif not duplicate["deadline_text"] and task["deadline_text"]:
            duplicate["deadline_text"] = task["deadline_text"]
    return result


# --- запасной вариант без LLM --------------------------------------------------

EXPLICIT_TASK = re.compile(
    r"(?P<what>[^.:;]{10,200}?)\s*[—–,-]\s*ответственн\w*\s+(?P<who>[^,;.]{2,60}),\s*срок\s+(?P<when>[^.;]{2,40})",
    re.IGNORECASE,
)


def rule_based_tasks(utterances: list[dict]) -> list[dict]:
    """Ловит только явную форму "что — ответственный X, срок Y". Нужна, чтобы протокол не был пустым без LLM."""
    tasks = []
    for u in utterances:
        for m in EXPLICIT_TASK.finditer(u["text"]):
            what = re.sub(r"^(?:\w+ое\s*[:–—-]|\d+[.):]?)\s*", "",
                          m.group("what").strip(), flags=re.IGNORECASE)
            tasks.append({"description": what, "assignee": m.group("who").strip(), "issuer": u["speaker"],
                          "deadline_text": m.group("when").strip(), "quote": m.group(0).strip(),
                          "priority": "medium", "category": "прочее"})
    return tasks


# --- основной сценарий ---------------------------------------------------------

def canonical_name(name: str, participants: list[str]) -> str:
    """Имя из речи -> написание из карточки совещания («Тимур Булотович» -> «Тимур Болатович»)."""
    if not name or not participants:
        return name
    names = [p.split("—")[0].split(" - ")[0].strip() for p in participants]
    best = max(names, key=lambda n: _similar(name, n))
    return best if _similar(name, best) >= 0.7 else name


def _participants_hint(participants: list[str]) -> str:
    if not participants:
        return ""
    return ("Участники совещания по карточке (используй это написание имён):\n"
            + "\n".join(f"- {p}" for p in participants) + "\n\n")


def analyze(utterances: list[dict], meeting_date: date, participants: list[str] | None = None) -> dict:
    participants = participants or []
    labels = sorted({u["speaker"] for u in utterances})
    speakers = [{"label": label, "name": "", "role": ""} for label in labels]
    summary: dict = {"overview": "", "topics": [], "decisions": []}
    raw_tasks: list[dict] = []
    llm_used = False
    hint = _participants_hint(participants)

    if utterances and llm.available():
        try:
            transcript = format_transcript(utterances)
            identified = llm.chat_json(SPEAKERS_SYSTEM, hint + transcript[:CHUNK_CHARS * 2], SPEAKERS_SCHEMA,
                                       "speakers")
            by_label = {s["label"]: s for s in identified.get("speakers", []) if s.get("label") in labels}
            speakers = [by_label.get(label, {"label": label, "name": "", "role": ""}) for label in labels]
            for s in speakers:
                s["name"] = canonical_name(s.get("name", ""), participants)
            names = {s["label"]: s["name"] for s in speakers if s.get("name")}

            lines = format_transcript(utterances, names).splitlines()
            for chunk in _chunks(lines):
                raw_tasks += llm.chat_json(TASKS_SYSTEM, hint + chunk, TASKS_SCHEMA, "tasks").get("tasks", [])

            summary = llm.chat_json(SUMMARY_SYSTEM, "\n".join(lines)[:CHUNK_CHARS * 2], SUMMARY_SCHEMA, "summary")
            llm_used = True
        except llm.LLMError as exc:
            log.error("LLM failed, falling back to rules: %s", exc)
            raw_tasks = []

    if not llm_used:
        raw_tasks = rule_based_tasks(utterances)
        summary["overview"] = ("Саммари недоступно: LLM не подключена (нет ключа или сервер не отвечает). "
                               "Поручения выделены по шаблонам — только явные формулировки.")

    tasks = []
    for t in raw_tasks:
        t["assignee"] = canonical_name(t.get("assignee", "").strip(), participants)
    for t in _dedupe([t for t in raw_tasks if t.get("description", "").strip()]):
        due = parse_deadline(t.get("deadline_text"), meeting_date)
        tasks.append({
            "description": t["description"].strip(),
            "assignee": t.get("assignee", "").strip() or None,
            "assignee_speaker": match_speaker(t.get("assignee", ""), speakers),
            "issuer_speaker": t.get("issuer") if t.get("issuer") in labels else None,
            "deadline_text": t.get("deadline_text", "").strip() or None,
            "due_date": due.isoformat() if due else None,
            "priority": t.get("priority"),
            "category": t.get("category"),
            "quote": t.get("quote"),
        })

    return {"speakers": speakers, "tasks": tasks, "summary": json.dumps(summary, ensure_ascii=False),
            "llm_used": llm_used}
