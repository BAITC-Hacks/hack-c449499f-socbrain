"""Self-hosted провайдер — целевой путь по ограничению ТЗ (без передачи
аудио наружу). faster_whisper импортируется только здесь, а не в
__init__.py — чтобы provider=external работал без этой (тяжёлой) зависимости.

Модель в Docker-образе worker встроена при сборке: в закрытом контуре
интернет на рантайме не нужен.
"""

import gc
import logging
from pathlib import Path

from .base import STTProvider, TranscriptResult, TranscriptSegment, TranscriptWord

log = logging.getLogger(__name__)


class FasterWhisperProvider(STTProvider):
    def __init__(self, model_size: str = "small", compute_type: str = "int8", language: str | None = None,
                 download_root: str | None = None, cpu_threads: int = 4):
        from faster_whisper import WhisperModel  # локальный импорт, см. докстринг модуля

        kwargs = dict(device="auto", compute_type=compute_type, download_root=download_root,
                      cpu_threads=cpu_threads)
        try:
            self._model = WhisperModel(model_size, local_files_only=True, **kwargs)
        except Exception:  # модели нет в образе — скачать (только вне закрытого контура)
            log.warning("whisper %s не встроен в образ, скачиваю", model_size)
            self._model = WhisperModel(model_size, **kwargs)
        self._language = language

    def transcribe(self, audio_path: Path, prompt: str | None = None) -> TranscriptResult:
        auto = self._language is None
        segments_iter, info = self._model.transcribe(
            str(audio_path),
            language=self._language,
            # Язык определяется по каждому фрагменту, а не один на файл:
            # шала-казахская речь переключается посреди совещания.
            multilingual=auto,
            word_timestamps=True,
            vad_filter=True,
            beam_size=5,
            initial_prompt=prompt,
            condition_on_previous_text=False,
        )

        segments, words = [], []
        for seg in segments_iter:
            segments.append(TranscriptSegment(start=seg.start, end=seg.end, text=seg.text))
            words += [TranscriptWord(w.start, w.end, w.word) for w in seg.words or [] if w.word.strip()]
        return TranscriptResult(language=info.language, segments=segments, words=words)

    def close(self) -> None:
        """Освободить память до запуска LLM — на слабом железе они не помещаются вместе."""
        del self._model
        gc.collect()
