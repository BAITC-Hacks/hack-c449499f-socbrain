import os

from .base import STTProvider, TranscriptResult, TranscriptSegment

__all__ = ["STTProvider", "TranscriptResult", "TranscriptSegment", "get_provider"]


def get_provider() -> STTProvider:
    """Выбор провайдера по STT_PROVIDER из окружения (см. .env.example).

    Остальной код обращается только сюда и к STTProvider — какая именно
    модель распознаёт речь, ему знать не нужно.
    """
    provider = os.getenv("STT_PROVIDER", "external").lower()

    if provider == "external":
        from .external_openai import OpenAIWhisperProvider

        return OpenAIWhisperProvider(api_key=os.getenv("OPENAI_API_KEY", ""))

    if provider == "local":
        from .local_faster_whisper import FasterWhisperProvider

        return FasterWhisperProvider()

    raise ValueError(f"Неизвестный STT_PROVIDER: {provider!r} (ожидается external или local)")
