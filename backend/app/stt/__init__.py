import os

from .base import STTProvider, TranscriptResult, TranscriptSegment, TranscriptWord

__all__ = ["STTProvider", "TranscriptResult", "TranscriptSegment", "TranscriptWord", "get_provider"]


def get_provider() -> STTProvider:
    """Выбор провайдера по STT_PROVIDER из окружения (см. .env.example).

    Остальной код обращается только сюда и к STTProvider — какая именно
    модель распознаёт речь, ему знать не нужно.
    """
    provider = os.getenv("STT_PROVIDER", "local").lower()

    if provider == "external":
        from .external_openai import OpenAIWhisperProvider

        return OpenAIWhisperProvider(api_key=os.getenv("OPENAI_API_KEY", ""))

    if provider == "local":
        from ..config import settings
        from .local_faster_whisper import FasterWhisperProvider

        return FasterWhisperProvider(
            model_size=settings.whisper_model,
            compute_type=settings.whisper_compute,
            language=settings.whisper_language,
            download_root=str(settings.models_dir / "whisper"),
            cpu_threads=settings.cpu_threads,
        )

    raise ValueError(f"Неизвестный STT_PROVIDER: {provider!r} (ожидается external или local)")
