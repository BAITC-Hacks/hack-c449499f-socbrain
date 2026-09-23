"""Сверка выделенных поручений с эталонным протоколом (.docx с таблицей «Поручение | Ответственный | Срок»).

    python -m app.evaluate <id совещания> "Протокол_совещания№1.docx" [--api http://localhost:8000]

Показывает, какие поручения найдены, какие пропущены и какие лишние, и
для найденных — совпал ли ответственный и срок. Нужна, чтобы видеть,
стало лучше или хуже после смены модели, промпта или настроек диаризации.
"""
import argparse
import difflib
import json
import re
import sys
import urllib.request
from datetime import date

from docx import Document

from .pipeline.dates import parse_deadline

MATCH_THRESHOLD = 0.45


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", " ", (text or "").lower())).strip()


def _similar(a: str, b: str) -> float:
    return difflib.SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def reference_tasks(path: str) -> list[dict]:
    tasks = []
    for table in Document(path).tables:
        header = [c.text.strip().lower() for c in table.rows[0].cells]
        if not header or "поручение" not in header[0]:
            continue
        for row in table.rows[1:]:
            cells = [c.text.strip() for c in row.cells]
            tasks.append({"description": cells[0], "assignee": cells[1], "deadline": cells[2]})
    return tasks


def _same_person(a: str, b: str) -> bool:
    first_a, first_b = _norm(a).split()[:1], _norm(b).split()[:1]
    return bool(first_a and first_a == first_b) or _similar(a, b) >= 0.7


def evaluate(meeting: dict, reference: list[dict]) -> dict:
    meeting_date = date.fromisoformat(meeting["meeting_date"])
    found = meeting["tasks"]
    pairs, used = [], set()
    # Жадное сопоставление: сначала самые похожие пары «эталон — найденное».
    scored = sorted(((_similar(r["description"], f["description"])
                      + (0.25 if _same_person(r["assignee"], f.get("assignee") or "") else 0), i, j)
                     for i, r in enumerate(reference) for j, f in enumerate(found)), reverse=True)
    matched_ref = set()
    for score, i, j in scored:
        if score < MATCH_THRESHOLD or i in matched_ref or j in used:
            continue
        matched_ref.add(i)
        used.add(j)
        pairs.append((reference[i], found[j]))

    rows = []
    for ref, got in pairs:
        ref_due = parse_deadline(ref["deadline"], meeting_date)
        rows.append({
            "reference": ref["description"], "found": got["description"],
            "assignee_ok": _same_person(ref["assignee"], got.get("assignee") or ""),
            "assignee": f'{ref["assignee"]} / {got.get("assignee") or "—"}',
            "deadline_ok": (ref_due is not None and got.get("due_date") == ref_due.isoformat())
                           or (ref_due is None and not got.get("due_date")),
            "deadline": f'{ref["deadline"]} / {got.get("due_date") or got.get("deadline_text") or "—"}',
        })
    missed = [r for i, r in enumerate(reference) if i not in matched_ref]
    extra = [f for j, f in enumerate(found) if j not in used]
    n = len(reference)
    return {
        "rows": rows, "missed": missed, "extra": extra,
        "recall": len(pairs) / n if n else 0.0,
        "precision": len(pairs) / len(found) if found else 0.0,
        "assignee_accuracy": sum(r["assignee_ok"] for r in rows) / len(rows) if rows else 0.0,
        "deadline_accuracy": sum(r["deadline_ok"] for r in rows) / len(rows) if rows else 0.0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("meeting_id")
    parser.add_argument("reference_docx")
    parser.add_argument("--api", default="http://localhost:8000")
    args = parser.parse_args()

    with urllib.request.urlopen(f"{args.api}/api/meetings/{args.meeting_id}") as response:
        meeting = json.load(response)
    result = evaluate(meeting, reference_tasks(args.reference_docx))

    mark = lambda ok: "✓" if ok else "✗"
    print(f"Совещание: {meeting['title']} ({meeting['meeting_date']}), LLM: {'да' if meeting['llm_used'] else 'нет'}\n")
    for r in result["rows"]:
        print(f"  найдено  {r['reference'][:70]}")
        print(f"           ответственный {mark(r['assignee_ok'])} {r['assignee']}")
        print(f"           срок          {mark(r['deadline_ok'])} {r['deadline']}")
    for r in result["missed"]:
        print(f"  ПРОПУЩЕНО {r['description'][:70]} ({r['assignee']}, {r['deadline']})")
    for f in result["extra"]:
        print(f"  лишнее    {f['description'][:70]} ({f.get('assignee') or '—'})")
    print(f"\nПолнота {result['recall']:.0%} · точность {result['precision']:.0%} · "
          f"ответственный верен {result['assignee_accuracy']:.0%} · срок верен {result['deadline_accuracy']:.0%}")
    sys.exit(0)


if __name__ == "__main__":
    main()
