"""Внешний провайдер (NVIDIA Riva / NVCF, whisper-large-v3) — временный,
для обкатки пайплайна на этапе разработки. НЕ для финальной сдачи: ТЗ
запрещает передачу аудио во внешние облачные API, а grpc.nvcf.nvidia.com
именно им и является, несмотря на то что модель называется NVIDIA.
См. .env.example.

Riva принимает только моно WAV/OPUS/FLAC — наши исходники mp3, поэтому
перед отправкой конвертируем через ffmpeg (должен быть в PATH).
"""

import subprocess
import tempfile
from pathlib import Path

import riva.client

from .base import STTProvider, TranscriptResult, TranscriptSegment

NVCF_SERVER = "grpc.nvcf.nvidia.com:443"
WHISPER_LARGE_V3_FUNCTION_ID = "b702f636-f60c-4a3d-a6f4-f3568c13bd7d"


def _to_riva_wav(audio_path: Path) -> Path:
    """ffmpeg: любой входной формат -> mono 16kHz 16-bit PCM WAV."""
    tmp = Path(tempfile.mktemp(suffix=".wav"))
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", str(audio_path), "-ac", "1", "-ar", "16000", "-sample_fmt", "s16", str(tmp)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg не смог сконвертировать {audio_path.name}: {result.stderr[-500:]}")
    return tmp


class NvidiaRivaProvider(STTProvider):
    def __init__(self, api_key: str, language_code: str = "ru"):
        if not api_key:
            raise ValueError(
                "NVIDIA_API_KEY не задан. Заполни .env (см. .env.example) "
                "или переключись на STT_PROVIDER=local."
            )
        auth = riva.client.Auth(
            uri=NVCF_SERVER,
            use_ssl=True,
            metadata_args=[
                ["function-id", WHISPER_LARGE_V3_FUNCTION_ID],
                ["authorization", f"Bearer {api_key}"],
            ],
        )
        self._service = riva.client.ASRService(auth)
        self._language_code = language_code

    def transcribe(self, audio_path: Path) -> TranscriptResult:
        wav_path = _to_riva_wav(audio_path)
        try:
            config = riva.client.RecognitionConfig(
                encoding=riva.client.AudioEncoding.LINEAR_PCM,
                sample_rate_hertz=16000,
                language_code=self._language_code,
                max_alternatives=1,
                enable_automatic_punctuation=True,
                audio_channel_count=1,
            )
            with open(wav_path, "rb") as f:
                data = f.read()
            response = self._service.offline_recognize(data, config)
        finally:
            wav_path.unlink(missing_ok=True)

        segments = []
        for result in response.results:
            if not result.alternatives:
                continue
            alt = result.alternatives[0]
            words = alt.words
            start = words[0].start_time / 1000 if words else 0.0
            end = words[-1].end_time / 1000 if words else 0.0
            segments.append(TranscriptSegment(start=start, end=end, text=alt.transcript))

        return TranscriptResult(language=self._language_code, segments=segments)
