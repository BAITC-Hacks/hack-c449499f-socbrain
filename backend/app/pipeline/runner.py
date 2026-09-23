"""Полный цикл обработки одной записи совещания."""
import logging
import shutil
from datetime import date

from .. import db
from ..config import settings
from ..stt import get_provider
from . import align, audio, diarization, extract, lang

log = logging.getLogger(__name__)


def participant_names(meeting: dict) -> list[str]:
    """Участники из карточки совещания: по строке на человека, «Имя — должность»."""
    lines = (meeting.get("participants") or "").replace(";", "\n").splitlines()
    return [line.strip() for line in lines if line.strip()]


def stt_prompt(meeting: dict) -> str:
    """Подсказка для распознавания: тема, имена участников и общий словарь из настроек."""
    names = [p.split("—")[0].split(" - ")[0].strip() for p in participant_names(meeting)]
    parts = [meeting["title"] + "."]
    if names:
        parts.append("Участники: " + ", ".join(names) + ".")
    parts.append(settings.whisper_prompt)
    return " ".join(parts)


def _analyze_and_save(meeting: dict, utterances: list[dict], language: str, duration: float) -> None:
    result = extract.analyze(utterances, date.fromisoformat(meeting["meeting_date"]), participant_names(meeting))
    db.save_result(meeting["id"], language=language, duration=duration, segments=utterances, **result)
    log.info("meeting %s done: %d utterances, %d tasks, llm=%s",
             meeting["id"], len(utterances), len(result["tasks"]), result["llm_used"])


def reanalyze(meeting: dict) -> None:
    """Повторный анализ готовой стенограммы (сменили LLM, промпт, участников) — без повторного распознавания."""
    meeting_id = meeting["id"]
    try:
        db.set_stage(meeting_id, "llm")
        utterances = db.rows("SELECT start, end, speaker, text, lang FROM segments WHERE meeting_id = ?"
                             " ORDER BY start", meeting_id)
        if not utterances:
            raise RuntimeError("нет стенограммы — нужна полная обработка")
        _analyze_and_save(meeting, utterances, meeting["language"], meeting["duration"])
    except Exception as exc:
        log.exception("meeting %s reanalysis failed", meeting_id)
        db.fail_meeting(meeting_id, f"{type(exc).__name__}: {exc}")


def process(meeting: dict) -> None:
    if meeting.get("stage") == "llm_only":
        return reanalyze(meeting)
    meeting_id = meeting["id"]
    work_dir = settings.work_dir / meeting_id
    try:
        db.set_stage(meeting_id, "convert")
        wav = audio.to_wav(settings.upload_dir / meeting["filename"], work_dir)

        db.set_stage(meeting_id, "asr")
        provider = get_provider()
        transcript = provider.transcribe(wav, prompt=stt_prompt(meeting))
        if hasattr(provider, "close"):
            provider.close()
        log.info("asr: %d words, language=%s", len(transcript.words), transcript.language)

        db.set_stage(meeting_id, "diarization")
        num_speakers = meeting["num_speakers"] or len(participant_names(meeting)) or settings.num_speakers
        try:
            turns = diarization.diarize(wav, num_speakers)
        except Exception:
            log.exception("diarization failed, continuing with a single speaker")
            turns = []
        utterances = align.to_utterances(transcript.words, turns)

        db.set_stage(meeting_id, "llm")
        language = lang.meeting_language(utterances) or transcript.language
        _analyze_and_save(meeting, utterances, language, audio.duration(wav))
    except Exception as exc:
        log.exception("meeting %s failed", meeting_id)
        db.fail_meeting(meeting_id, f"{type(exc).__name__}: {exc}")
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
