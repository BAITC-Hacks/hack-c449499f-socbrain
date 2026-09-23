"""Прогнать один аудиофайл совещания через настроенный STT-провайдер.

Использование:
    python -m app.transcribe "путь/к/записи.mp3"

Результат печатается в консоль и сохраняется рядом с исходным файлом
как <имя>.transcript.txt (реплики с таймкодами, без диаризации —
она следующим шагом поверх этого текста).
"""

import sys
from pathlib import Path

from dotenv import load_dotenv

from app.ai_connections import get_default_provider_or_env_fallback


def format_timestamp(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    return f"{m:02d}:{s:02d}"


def main() -> None:
    if len(sys.argv) != 2:
        print("Использование: python -m app.transcribe <путь к аудио>")
        sys.exit(1)

    audio_path = Path(sys.argv[1])
    if not audio_path.exists():
        print(f"Файл не найден: {audio_path}")
        sys.exit(1)

    load_dotenv()

    provider = get_default_provider_or_env_fallback()
    print(f"Распознаю {audio_path.name} через {type(provider).__name__}...")

    result = provider.transcribe(audio_path)

    lines = [
        f"[{format_timestamp(seg.start)}–{format_timestamp(seg.end)}] {seg.text.strip()}"
        for seg in result.segments
    ]
    output = "\n".join(lines)

    print(f"\nЯзык: {result.language}")
    print(output)

    out_path = audio_path.with_suffix(".transcript.txt")
    out_path.write_text(output, encoding="utf-8")
    print(f"\nСохранено: {out_path}")


if __name__ == "__main__":
    main()
