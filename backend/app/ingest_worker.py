"""Consume completed recordings using only the existing local STT implementation."""
from dataclasses import asdict
import logging
import os
from pathlib import Path
import signal
import threading

from .ingest_store import Store


def process_one(store, provider):
    job = store.claim()
    if job is None:
        return False
    try:
        result = provider.transcribe(store.directory / job["filename"])
        store.finish(job["id"], {"language": result.language, "text": result.text,
                                "segments": [asdict(segment) for segment in result.segments]})
    except Exception:
        store.fail(job["id"])
        logging.error("Local STT failed for recording %s", job["id"])
    return True


def main():
    import fcntl
    from .stt.local_faster_whisper import FasterWhisperProvider

    directory = Path(os.getenv("INGEST_DATA_DIR", "/data"))
    store = Store(directory)
    with (directory / "stt-worker.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        model = os.getenv("WHISPER_MODEL", "/models/faster-whisper-small")
        if not Path(model).is_dir():
            raise ValueError("WHISPER_MODEL must point to a preloaded local model directory")
        provider = FasterWhisperProvider(model_size=model, device=os.getenv("WHISPER_DEVICE", "cpu"),
                                         compute_type=os.getenv("WHISPER_COMPUTE_TYPE", "int8"))
        store.recover()
        stop = threading.Event()
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        while not stop.is_set():
            if not process_one(store, provider):
                stop.wait(2)


if __name__ == "__main__":
    main()
