from datetime import datetime, timezone
import json
import logging
import os
from pathlib import Path
import signal
import threading
import wave

from .config import Settings
from .delivery import Delivery, DeliveryError
from .store import Store

log = logging.getLogger("zoom-rtms-worker")


class SessionFiles:
    def __init__(self, directory, key):
        self.wav_path = Path(directory) / (key + ".wav")
        self.transcript_path = Path(directory) / (key + ".transcript.jsonl")
        self.events_path = Path(directory) / (key + ".events.jsonl")
        self.lock, self.last_timestamp, self.closed = threading.Lock(), None, False
        self.wav = wave.open(str(self.wav_path), "wb")
        self.wav.setnchannels(1)
        self.wav.setsampwidth(2)
        self.wav.setframerate(16000)

    def audio(self, data, size, timestamp, _metadata):
        with self.lock:
            if self.closed:
                return
            if self.last_timestamp is not None:
                gap = int(timestamp) - self.last_timestamp - 20
                if 40 <= gap <= 10000:
                    self.wav.writeframesraw(b"\0\0" * (gap * 16))
            self.wav.writeframesraw(bytes(data[:size]))
            self.last_timestamp = int(timestamp)

    def transcript(self, data, size, timestamp, metadata):
        self._json(self.transcript_path, {"timestamp": int(timestamp), "user_id": int(metadata.userId),
            "user_name": str(metadata.userName), "text": bytes(data[:size]).decode("utf-8", "replace")})

    def speaker(self, timestamp, user_id, user_name):
        self._json(self.events_path, {"event": "active_speaker", "timestamp": int(timestamp),
                                     "user_id": int(user_id), "user_name": str(user_name)})

    def participants(self, event, timestamp, participants):
        self._json(self.events_path, {"event": "participant_" + str(event), "timestamp": int(timestamp),
                                     "participants": participants})

    def _json(self, path, value):
        with self.lock:
            if self.closed:
                return
            with path.open("a", encoding="utf-8") as output:
                output.write(json.dumps(value, ensure_ascii=False) + "\n")
                output.flush()

    def close(self):
        with self.lock:
            if not self.closed:
                self.closed = True
                self.wav.close()


class LiveSession:
    def __init__(self, rtms, row, directory):
        self.rtms, self.row = rtms, row
        self.files = SessionFiles(directory, row["id"])
        self.ended = threading.Event()
        self.client = rtms.Client()
        self.loop = rtms.EventLoop(name="zoom-" + row["id"][:8])
        params = rtms.AudioParams(content_type=2, codec=1, sample_rate=1, channel=1,
                                  data_opt=1, duration=20, frame_size=320)
        self.client.set_audio_params(params)
        self.client.enable_audio(True)
        self.client.enable_transcript(True)
        self.client.on_audio_data(self.files.audio)
        self.client.on_transcript_data(self.files.transcript)
        self.client.on_active_speaker_event(self.files.speaker)
        self.client.on_participant_event(self.files.participants)
        self.client.on_leave(lambda _reason: self.ended.set())
        self.loop.add(self.client)

    def start(self):
        joined = self.client.join(self.row["payload"])
        if not joined:
            self.files.close()
            return False
        self.loop.start()
        return True

    def close(self):
        try:
            self.client.leave()
        finally:
            self.loop.stop()
            self.loop.join(timeout=10)
            self.files.close()


def finalize(store, delivery, key, session, row):
    session.close()
    try:
        if not session.files.wav_path.is_file() or session.files.wav_path.stat().st_size <= 44:
            raise OSError("No RTMS audio")
        result = delivery.upload(session.files.wav_path, row["title"], row["meeting_date"],
                                 "zoom-rtms-" + key, "zoom-rtms")
        store.set_rtms(key, "delivered", result=result)
    except (DeliveryError, OSError):
        store.set_rtms(key, "finished", "Live transcript retained; WAV delivery failed")


def finalize_orphan(store, delivery, row, directory):
    path = Path(directory) / (row["id"] + ".wav")
    try:
        if not path.is_file() or path.stat().st_size <= 44:
            store.set_rtms(row["id"], "finished", "RTMS stopped before audio was captured")
            return
        result = delivery.upload(path, row["title"], row["meeting_date"],
                                 "zoom-rtms-" + row["id"], "zoom-rtms")
        store.set_rtms(row["id"], "delivered", result=result)
    except (DeliveryError, OSError):
        store.set_rtms(row["id"], "finished", "Live artifacts retained; WAV delivery failed")


def main():
    import fcntl
    import rtms
    logging.basicConfig(level=logging.INFO)
    settings = Settings.from_env()
    settings.validate("rtms")
    os.environ["ZM_RTMS_CLIENT"] = settings.rtms_client_id
    os.environ["ZM_RTMS_SECRET"] = settings.rtms_client_secret
    store, delivery = Store(settings.data_dir), Delivery(settings)
    active, stop = {}, threading.Event()
    with (settings.data_dir / "zoom-rtms-worker.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        store.recover_rtms()
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        try:
            while not stop.is_set():
                for row in store.pending_rtms():
                    if row["id"] in active:
                        continue
                    try:
                        session = LiveSession(rtms, row, settings.data_dir)
                        if session.start():
                            active[row["id"]] = (session, row)
                            store.set_rtms(row["id"], "running")
                        else:
                            store.set_rtms(row["id"], "error", "Zoom RTMS SDK rejected the stream")
                    except Exception:
                        log.exception("Unable to start RTMS stream %s", row["id"])
                        store.set_rtms(row["id"], "error", "Unable to initialize Zoom RTMS stream")
                stopping = {row["id"]: row for row in store.stopping_rtms()}
                for key, (session, row) in list(active.items()):
                    if key in stopping or session.ended.is_set():
                        finalize(store, delivery, key, session, row)
                        active.pop(key, None)
                for key, row in stopping.items():
                    if key not in active:
                        finalize_orphan(store, delivery, row, settings.data_dir)
                stop.wait(0.2)
        finally:
            for key, (session, row) in list(active.items()):
                session.close()
                store.set_rtms(key, "pending", "RTMS worker stopped; reconnect will be attempted")
            delivery.close()


if __name__ == "__main__":
    main()
