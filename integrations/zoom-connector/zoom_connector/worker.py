import logging
import os
from pathlib import Path
import signal
import threading
import time
from urllib.parse import urljoin, urlparse

import httpx

from .config import Settings
from .delivery import Delivery, DeliveryError
from .store import Store
from .zoom_api import ZoomAPI, ZoomError

log = logging.getLogger("zoom-worker")


def download_recording(api, job, target, max_bytes):
    partial = target.with_suffix(target.suffix + ".part")
    partial.unlink(missing_ok=True)
    url, headers = job["download_url"], {"Authorization": "Bearer " + api.token()}
    try:
        for _ in range(6):
            with api.client.stream("GET", url, headers=headers) as response:
                if response.status_code in {301, 302, 303, 307, 308}:
                    location = response.headers.get("location")
                    if not location:
                        raise ZoomError("Zoom download redirect has no location")
                    url = urljoin(url, location)
                    if urlparse(url).scheme != "https":
                        raise ZoomError("Zoom download redirected to a non-HTTPS URL")
                    headers = {}  # Never forward the Zoom token to object storage.
                    continue
                if response.status_code != 200:
                    raise ZoomError(f"Zoom recording download failed with HTTP {response.status_code}")
                advertised = int(response.headers.get("content-length") or 0)
                if advertised > max_bytes:
                    raise ZoomError("Zoom recording is larger than ZOOM_MAX_DOWNLOAD_BYTES")
                size = 0
                with partial.open("xb") as output:
                    for chunk in response.iter_bytes(1024 * 1024):
                        size += len(chunk)
                        if size > max_bytes:
                            raise ZoomError("Zoom recording exceeded ZOOM_MAX_DOWNLOAD_BYTES")
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
                if size == 0:
                    raise ZoomError("Zoom returned an empty recording")
                partial.replace(target)
                return target
        raise ZoomError("Too many Zoom recording redirects")
    except BaseException:
        partial.unlink(missing_ok=True)
        raise


def process_recording(store, api, delivery, settings):
    job = store.claim_recording()
    if not job:
        return False
    target = settings.data_dir / job["filename"]
    try:
        download_recording(api, job, target, settings.max_download_bytes)
        result = delivery.upload(target, job["title"], job["meeting_date"], job["id"], "zoom-cloud")
        store.set_recording(job["id"], "delivered", result=result)
    except (ZoomError, DeliveryError, httpx.RequestError, OSError) as error:
        terminal = int(job["attempts"]) + 1 >= 8
        store.set_recording(job["id"], "failed" if terminal else "retry",
                            "Processing failed; retry limit reached" if terminal else "Temporary processing failure; will retry")
        log.warning("Cloud recording job %s failed: %s", job["id"], type(error).__name__)
    finally:
        target.unlink(missing_ok=True)
    return True


def refresh_calendar(store, api, user_ids):
    for user_id in user_ids:
        try:
            store.replace_calendar(user_id, api.calendar(user_id))
        except (ZoomError, httpx.RequestError):
            log.warning("Calendar refresh failed for configured Zoom user")


def process_rtms_start(store, api, settings):
    action = store.claim_rtms_start()
    if not action:
        return False
    try:
        api.start_rtms(action["meeting_id"], settings.rtms_client_id)
        store.set_rtms_start(action["meeting_id"], "started")
    except (ZoomError, httpx.RequestError):
        terminal = int(action["attempts"]) + 1 >= 5
        store.set_rtms_start(action["meeting_id"], "failed" if terminal else "retry",
                             "RTMS start failed; verify invitee/host permissions")
    return True


def main():
    import fcntl
    logging.basicConfig(level=logging.INFO)
    settings = Settings.from_env()
    settings.validate("worker")
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    store = Store(settings.data_dir)
    with (settings.data_dir / "zoom-worker.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        store.recover_recordings()
        api, delivery = ZoomAPI(settings), Delivery(settings)
        stop = threading.Event()
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        next_calendar = 0.0
        try:
            while not stop.is_set():
                if time.monotonic() >= next_calendar:
                    refresh_calendar(store, api, settings.user_ids)
                    next_calendar = time.monotonic() + settings.calendar_poll_seconds
                process_recording(store, api, delivery, settings)
                if settings.rtms_auto_start:
                    process_rtms_start(store, api, settings)
                stop.wait(settings.worker_poll_seconds)
        finally:
            api.close()
            delivery.close()


if __name__ == "__main__":
    main()
