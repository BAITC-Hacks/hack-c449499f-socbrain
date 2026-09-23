from datetime import datetime, timezone
import hashlib
from pathlib import Path
from urllib.parse import urlparse


def select_recording(obj, priorities):
    files = [item for item in obj.get("recording_files", []) if isinstance(item, dict)
             and item.get("status", "completed") == "completed" and item.get("download_url")]
    for preferred in priorities:
        for item in files:
            kinds = {str(item.get("file_type") or "").upper(), str(item.get("recording_type") or "").upper()}
            if preferred in kinds:
                return item
    return None


def recording_job(event, priorities):
    payload = event.get("payload") or {}
    obj = payload.get("object") or {}
    item = select_recording(obj, priorities)
    if not item:
        return None
    url = str(item["download_url"])
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or not (
            parsed.hostname == "zoom.us" or parsed.hostname.endswith(".zoom.us")):
        raise ValueError("Recording download URL is not an HTTPS Zoom URL")
    meeting_uuid = str(obj.get("uuid") or obj.get("id") or "")
    if not meeting_uuid:
        raise ValueError("Recording event has no meeting identifier")
    file_id = str(item.get("id") or hashlib.sha256(url.encode()).hexdigest())
    job_id = hashlib.sha256((meeting_uuid + ":" + file_id).encode()).hexdigest()[:32]
    kind = str(item.get("file_type") or "M4A").lower()
    suffix = "." + ({"audio_only": "m4a"}.get(kind, kind) if kind.isalnum() else "bin")
    if suffix not in {".m4a", ".mp4", ".mp3", ".wav", ".ogg", ".opus", ".webm", ".flac"}:
        suffix = ".m4a" if str(item.get("recording_type", "")).lower() == "audio_only" else ".mp4"
    started = str(obj.get("start_time") or obj.get("recording_start") or "")
    try:
        meeting_date = datetime.fromisoformat(started.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        meeting_date = datetime.now(timezone.utc).date().isoformat()
    return {"id": job_id, "meeting_uuid": meeting_uuid,
            "title": str(obj.get("topic") or "Zoom meeting")[:300], "meeting_date": meeting_date,
            "filename": job_id + suffix, "download_url": url}
