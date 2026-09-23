import os

from .base import STTProvider, TranscriptResult, TranscriptSegment

__all__ = ["STTProvider", "TranscriptResult", "TranscriptSegment", "get_provider"]


def get_provider() -> STTProvider:
    """Выбор провайдера по STT_PROVIDER из окружения (см. .env.example).

    Остальной код обращается только сюда и к STTProvider — какая именно
    модель распознаёт речь, ему знать не нужно.
    """
    provider = os.getenv("STT_PROVIDER", "external_openai").lower()

    if provider in ("external", "external_openai"):
        from .external_openai import OpenAIWhisperProvider

        return OpenAIWhisperProvider(api_key=os.getenv("OPENAI_API_KEY", ""))

    if provider == "external_nvidia":
        from .external_nvidia_riva import NvidiaRivaProvider

        return NvidiaRivaProvider(
            api_key=os.getenv("NVIDIA_API_KEY", ""),
            language_code=os.getenv("NVIDIA_LANGUAGE_CODE", "ru"),
        )

    if provider == "local":
        from .local_faster_whisper import FasterWhisperProvider

        return FasterWhisperProvider()

    raise ValueError(
        f"Неизвестный STT_PROVIDER: {provider!r} "
        "(ожидается external_openai, external_nvidia или local)"
    )
