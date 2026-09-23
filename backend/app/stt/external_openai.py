"""Внешний провайдер (OpenAI Whisper API) — временный, для обкатки пайплайна
на этапе разработки. НЕ для финальной сдачи: ТЗ запрещает передачу аудио
во внешние облачные API. См. .env.example.

Известное ограничение: whisper-1 не заявляет официальную поддержку
казахского языка — на русском ожидаемо работает нормально, на
казахском/шала-казахском результат не показателен.
"""

from pathlib import Path

from openai import OpenAI

from .base import STTProvider, TranscriptResult, TranscriptSegment, TranscriptWord


class OpenAIWhisperProvider(STTProvider):
    def __init__(self, api_key: str, model: str = "whisper-1"):
        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY не задан. Заполни .env (см. .env.example) "
                "или переключись на STT_PROVIDER=local."
            )
        self._client = OpenAI(api_key=api_key)
        self._model = model

    def transcribe(self, audio_path: Path, prompt: str | None = None) -> TranscriptResult:
        with open(audio_path, "rb") as f:
            response = self._client.audio.transcriptions.create(
                model=self._model,
                file=f,
                response_format="verbose_json",
                timestamp_granularities=["segment", "word"],
                **({"prompt": prompt} if prompt else {}),
            )

        segments = [
            TranscriptSegment(start=seg.start, end=seg.end, text=seg.text)
            for seg in response.segments or []
        ]
        words = [TranscriptWord(w.start, w.end, " " + w.word) for w in response.words or []]
        return TranscriptResult(language=response.language, segments=segments, words=words)
