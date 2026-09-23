import subprocess
import wave
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16000


def to_wav(source: Path, work_dir: Path) -> Path:
    """Любой аудио/видеофайл -> WAV 16 кГц моно (формат, который ждут ASR и диаризация)."""
    work_dir.mkdir(parents=True, exist_ok=True)
    target = work_dir / "audio.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error", "-i", str(source),
         "-vn", "-ac", "1", "-ar", str(SAMPLE_RATE), "-sample_fmt", "s16", str(target)],
        check=True,
    )
    return target


def load_samples(wav_path: Path) -> np.ndarray:
    with wave.open(str(wav_path)) as f:
        frames = f.readframes(f.getnframes())
    return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0


def duration(wav_path: Path) -> float:
    with wave.open(str(wav_path)) as f:
        return f.getnframes() / f.getframerate()
