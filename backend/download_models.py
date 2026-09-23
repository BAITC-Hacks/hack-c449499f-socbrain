"""Скачивает модели ASR и диаризации в MODELS_DIR (вызывается при сборке образа worker)."""
import argparse
import os
import tarfile
import urllib.request
from pathlib import Path

SHERPA = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
SEGMENTATION_URL = f"{SHERPA}/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2"
EMBEDDING_URL = f"{SHERPA}/speaker-recongition-models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx"


def fetch(url: str, dest: Path) -> Path:
    if not dest.exists():
        print(f"download {url}")
        urllib.request.urlretrieve(url, dest)
    return dest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--whisper", default="small")
    args = parser.parse_args()

    root = Path(os.getenv("MODELS_DIR", "/models"))
    diar = root / "diarization"
    diar.mkdir(parents=True, exist_ok=True)

    archive = fetch(SEGMENTATION_URL, diar / "segmentation.tar.bz2")
    with tarfile.open(archive) as tar:
        tar.extractall(diar, filter="data")
    archive.unlink()
    fetch(EMBEDDING_URL, diar / "embedding.onnx")

    from faster_whisper.utils import download_model

    print(f"download whisper {args.whisper}")
    download_model(args.whisper, cache_dir=str(root / "whisper"))


if __name__ == "__main__":
    main()
