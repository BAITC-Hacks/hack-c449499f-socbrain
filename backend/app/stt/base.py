from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TranscriptWord:
    start: float  # секунды от начала записи
    end: float
    text: str     # как отдал движок, с ведущим пробелом


@dataclass
class TranscriptSegment:
    start: float  # секунды от начала записи
    end: float
    text: str


@dataclass
class TranscriptResult:
    language: str
    segments: list[TranscriptSegment]
    # Пословные таймкоды нужны диаризации: сегмент движок склеивает по
    # полминуты, и внутри одного успевают высказаться двое. Каждое слово
    # потом относится к тому говорящему, с чьей речью оно пересекается.
    words: list[TranscriptWord] = field(default_factory=list)

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
    def transcribe(self, audio_path: Path, prompt: str | None = None) -> TranscriptResult:
        """prompt — словарь-подсказка: имена участников, названия объектов.

        На своей лексике заметно поднимает точность: без подсказки модель
        пишет то, что похоже по звуку («Булотович» вместо «Болатович»).
        """
        raise NotImplementedError
