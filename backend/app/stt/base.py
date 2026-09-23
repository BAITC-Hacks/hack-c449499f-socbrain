from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TranscriptSegment:
    start: float  # секунды от начала записи
    end: float
    text: str


@dataclass
class TranscriptResult:
    language: str
    segments: list[TranscriptSegment]

    @property
    def text(self) -> str:
        return " ".join(s.text.strip() for s in self.segments)


class STTProvider(ABC):
    """Общий интерфейс распознавания речи.

    Любая реализация (внешняя или self-hosted) отдаёт один и тот же
    TranscriptResult — остальной пайплайн (диаризация, извлечение
    поручений) не знает и не должен знать, какой именно провайдер
    распознавал речь.
    """

    @abstractmethod
    def transcribe(self, audio_path: Path) -> TranscriptResult:
        raise NotImplementedError
