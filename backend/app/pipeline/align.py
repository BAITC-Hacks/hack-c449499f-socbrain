"""Склейка результатов ASR и диаризации в реплики "говорящий: текст"."""
from ..stt import TranscriptWord as Word
from . import lang
from .diarization import Turn

MAX_PAUSE = 1.5  # сек: пауза длиннее — новая реплика даже у того же говорящего


def _speaker_for(word: Word, turns: list[Turn]) -> str:
    """Говорящий с максимальным перекрытием слова; если перекрытия нет — ближайший по времени."""
    best, best_overlap = None, 0.0
    for turn in turns:
        overlap = min(word.end, turn.end) - max(word.start, turn.start)
        if overlap > best_overlap:
            best, best_overlap = turn.speaker, overlap
    if best:
        return best
    middle = (word.start + word.end) / 2
    nearest = min(turns, key=lambda t: min(abs(middle - t.start), abs(middle - t.end)))
    return nearest.speaker


def to_utterances(words: list[Word], turns: list[Turn]) -> list[dict]:
    utterances: list[dict] = []
    for word in words:
        speaker = _speaker_for(word, turns) if turns else "SPEAKER_00"
        last = utterances[-1] if utterances else None
        if last and last["speaker"] == speaker and word.start - last["end"] <= MAX_PAUSE:
            last["text"] += word.text
            last["end"] = word.end
        else:
            utterances.append({"start": word.start, "end": word.end, "speaker": speaker, "text": word.text})
    for u in utterances:
        u["text"] = u["text"].strip()
        u["lang"] = lang.detect(u["text"])
    return utterances


def format_transcript(utterances: list[dict], names: dict[str, str] | None = None) -> str:
    """Текст для LLM и протокола: '[мм:сс] SPEAKER_01 (Имя): реплика'."""
    names = names or {}
    lines = []
    for u in utterances:
        minutes, seconds = divmod(int(u["start"]), 60)
        who = u["speaker"] + (f" ({names[u['speaker']]})" if names.get(u["speaker"]) else "")
        lines.append(f"[{minutes:02d}:{seconds:02d}] {who}: {u['text']}")
    return "\n".join(lines)
