"""Self-hosted провайдер — целевой путь по ограничению ТЗ (без передачи
аудио наружу). Требует `pip install -r requirements-local.txt`, поэтому
faster_whisper импортируется только здесь, а не в __init__.py — чтобы
provider=external продолжал работать без этой (тяжёлой) зависимости.

Не проверено на реальном железе — заготовка под следующий шаг.
"""

from pathlib import Path

from .base import STTProvider, TranscriptResult, TranscriptSegment


class FasterWhisperProvider(STTProvider):
    def __init__(self, model_size: str = "large-v3", device: str = "auto", compute_type: str = "auto"):
        from faster_whisper import WhisperModel  # локальный импорт, см. докстринг модуля

        self._model = WhisperModel(model_size, device=device, compute_type=compute_type)

    def transcribe(self, audio_path: Path) -> TranscriptResult:
        segments_iter, info = self._model.transcribe(str(audio_path), beam_size=5)

        segments = [
            TranscriptSegment(start=seg.start, end=seg.end, text=seg.text)
            for seg in segments_iter
        ]
        return TranscriptResult(language=info.language, segments=segments)
