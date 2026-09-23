import json


def summary_of(meeting: dict) -> dict:
    try:
        return json.loads(meeting.get("summary") or "{}")
    except json.JSONDecodeError:
        return {"overview": meeting.get("summary") or ""}


def speaker_names(meeting: dict) -> dict[str, str]:
    return {s["label"]: (s["name"] or s["label"]) for s in meeting["speakers"]}


def timecode(seconds: float) -> str:
    minutes, secs = divmod(int(seconds), 60)
    return f"{minutes:02d}:{secs:02d}"


def task_rows(meeting: dict) -> list[list[str]]:
    rows = []
    for i, t in enumerate(meeting["tasks"], 1):
        due = t["due_date"] or ""
        if t["deadline_text"] and t["deadline_text"] != due:
            due = f"{due} ({t['deadline_text']})".strip() if due else t["deadline_text"]
        rows.append([str(i), t["description"], t["assignee"] or "—", due or "не указан"])
    return rows
