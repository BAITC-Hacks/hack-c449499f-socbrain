"""Диаризация (кто когда говорил): sherpa-onnx = сегментация pyannote-3.0 + эмбеддинги 3D-Speaker.

Всё в ONNX на CPU, без токенов HuggingFace и облака.
"""
import logging
from dataclasses import dataclass
from pathlib import Path

from ..config import settings

log = logging.getLogger(__name__)

MIN_TALK_SECONDS = 3.0  # меньше — не участник, а шум кластеризации


@dataclass
class Turn:
    start: float
    end: float
    speaker: str


def _label(index: int) -> str:
    return f"SPEAKER_{index:02d}"


def diarize(wav_path: Path, num_speakers: int = 0) -> list[Turn]:
    import sherpa_onnx

    from .audio import SAMPLE_RATE, load_samples

    models = settings.models_dir / "diarization"
    config = sherpa_onnx.OfflineSpeakerDiarizationConfig(
        segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
            pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                model=str(models / "sherpa-onnx-pyannote-segmentation-3-0" / "model.onnx"),
            ),
            num_threads=settings.cpu_threads,
        ),
        embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
            model=str(models / "embedding.onnx"),
            num_threads=settings.cpu_threads,
        ),
        clustering=sherpa_onnx.FastClusteringConfig(
            num_clusters=num_speakers if num_speakers > 0 else -1,
            threshold=settings.diarization_threshold,
        ),
        min_duration_on=0.3,
        min_duration_off=0.5,
    )
    if not config.validate():
        raise RuntimeError(f"invalid diarization config, models dir: {models}")

    diarizer = sherpa_onnx.OfflineSpeakerDiarization(config)
    assert diarizer.sample_rate == SAMPLE_RATE
    result = diarizer.process(load_samples(wav_path)).sort_by_start_time()
    turns = merge_minor_speakers([Turn(r.start, r.end, _label(r.speaker)) for r in result])
    log.info("diarization: %d turns, %d speakers", len(turns), len({t.speaker for t in turns}))
    return turns


def merge_minor_speakers(turns: list[Turn], min_talk: float = MIN_TALK_SECONDS) -> list[Turn]:
    """Свести «голоса», набравшие секунды речи, к соседним говорящим.

    Кластеризация принимает за отдельного человека кашель, эхо, короткое
    «хорошо» на переходе реплик. Такой «участник» с парой секунд речи только
    мешает: его реплика отходит ближайшему по времени основному говорящему —
    приписать полсекунды не тому хуже, чем плодить несуществующих людей.
    (Подход из aster_zapis, diarization/server.py:limit_speakers.)
    """
    talk: dict[str, float] = {}
    for t in turns:
        talk[t.speaker] = talk.get(t.speaker, 0.0) + t.end - t.start
    main = {s for s, seconds in talk.items() if seconds >= min_talk}
    if not main or len(main) == len(talk):
        return turns

    ordered = sorted(turns, key=lambda t: t.start)
    for i, t in enumerate(ordered):
        if t.speaker in main:
            continue
        before = next((ordered[j] for j in range(i - 1, -1, -1) if ordered[j].speaker in main), None)
        after = next((ordered[j] for j in range(i + 1, len(ordered)) if ordered[j].speaker in main), None)
        if before and after:
            closer = before if t.start - before.end <= after.start - t.end else after
        else:
            closer = before or after
        t.speaker = closer.speaker
    return ordered
