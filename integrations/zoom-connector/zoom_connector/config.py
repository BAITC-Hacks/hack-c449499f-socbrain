from dataclasses import dataclass
import os
from pathlib import Path
from urllib.parse import urlparse


def _bool(name, default=False):
    value = os.getenv(name)
    return default if value is None else value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    account_id: str
    client_id: str
    client_secret: str
    webhook_secret: str
    api_key: str
    data_dir: Path
    user_ids: tuple[str, ...]
    calendar_poll_seconds: int
    recording_types: tuple[str, ...]
    max_download_bytes: int
    participants_notified: bool
    app_upload_url: str
    app_api_key: str
    app_allow_http: bool
    app_ca_file: str
    rtms_enabled: bool
    rtms_client_id: str
    rtms_client_secret: str
    rtms_auto_start: bool
    worker_poll_seconds: float

    @classmethod
    def from_env(cls):
        return cls(
            account_id=os.getenv("ZOOM_ACCOUNT_ID", "").strip(),
            client_id=os.getenv("ZOOM_CLIENT_ID", "").strip(),
            client_secret=os.getenv("ZOOM_CLIENT_SECRET", "").strip(),
            webhook_secret=os.getenv("ZOOM_WEBHOOK_SECRET", "").strip(),
            api_key=os.getenv("ZOOM_CONNECTOR_API_KEY", ""),
            data_dir=Path(os.getenv("ZOOM_DATA_DIR", "/data")),
            user_ids=tuple(x.strip() for x in os.getenv("ZOOM_USER_IDS", "").split(",") if x.strip()),
            calendar_poll_seconds=int(os.getenv("CALENDAR_POLL_SECONDS", "300")),
            recording_types=tuple(x.strip().upper() for x in
                                  os.getenv("ZOOM_RECORDING_TYPES", "AUDIO_ONLY,M4A,MP4").split(",") if x.strip()),
            max_download_bytes=int(os.getenv("ZOOM_MAX_DOWNLOAD_BYTES", "2147483648")),
            participants_notified=_bool("PARTICIPANTS_NOTIFIED"),
            app_upload_url=os.getenv("APP_UPLOAD_URL", "").strip(),
            app_api_key=os.getenv("APP_API_KEY", ""),
            app_allow_http=_bool("APP_ALLOW_HTTP"),
            app_ca_file=os.getenv("APP_CA_FILE", "").strip(),
            rtms_enabled=_bool("ZOOM_RTMS_ENABLED"),
            rtms_client_id=os.getenv("ZOOM_RTMS_CLIENT_ID", os.getenv("ZOOM_CLIENT_ID", "")).strip(),
            rtms_client_secret=os.getenv("ZOOM_RTMS_CLIENT_SECRET", os.getenv("ZOOM_CLIENT_SECRET", "")).strip(),
            rtms_auto_start=_bool("ZOOM_RTMS_AUTO_START"),
            worker_poll_seconds=float(os.getenv("WORKER_POLL_SECONDS", "2")),
        )

    def validate(self, service="api"):
        if len(self.api_key) < 32:
            raise ValueError("ZOOM_CONNECTOR_API_KEY must contain at least 32 characters")
        if len(self.webhook_secret) < 16:
            raise ValueError("ZOOM_WEBHOOK_SECRET is required")
        if self.calendar_poll_seconds < 30 or self.worker_poll_seconds <= 0 or self.max_download_bytes <= 0:
            raise ValueError("Poll intervals and download limit must be positive")
        if service in {"worker", "rtms"}:
            if not all((self.account_id, self.client_id, self.client_secret)):
                raise ValueError("ZOOM_ACCOUNT_ID, ZOOM_CLIENT_ID and ZOOM_CLIENT_SECRET are required")
            if not self.participants_notified:
                raise ValueError("Set PARTICIPANTS_NOTIFIED=true after configuring participant notice")
        if service in {"worker", "rtms"}:
            target = urlparse(self.app_upload_url)
            if not target.hostname or target.scheme not in ({"https", "http"} if self.app_allow_http else {"https"}):
                raise ValueError("APP_UPLOAD_URL must be HTTPS unless APP_ALLOW_HTTP=true")
            if len(self.app_api_key) < 32:
                raise ValueError("APP_API_KEY must contain at least 32 characters")
        if service == "rtms" and (not self.rtms_enabled or not self.rtms_client_id or not self.rtms_client_secret):
            raise ValueError("Enable RTMS and set its client credentials")
