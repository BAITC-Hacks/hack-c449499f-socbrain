from dataclasses import dataclass, field
import os
from pathlib import Path
from urllib.parse import urlsplit
from uuid import UUID


@dataclass
class AutomationSettings:
    enabled: bool = False
    notified: bool = False
    data_dir: Path = Path("/data")
    spaces: set = field(default_factory=set)
    poll_seconds: int = 15
    schedule_limit: int = 1000
    sip_domain: str = ""
    sip_transport: str = "udp"
    upload_url: str = ""
    upload_key: str = field(default="", repr=False)
    upload_ca: str = ""
    upload_contract: str = "gateway"
    allow_http: bool = False
    upload_idempotent: bool = False

    @classmethod
    def from_env(cls):
        return cls(enabled=os.getenv("ASSISTANT_ENABLED", "false").lower() == "true",
            notified=os.getenv("PARTICIPANTS_NOTIFIED", "false").lower() == "true",
            data_dir=Path(os.getenv("CONNECTOR_DATA_DIR", "/data")),
            spaces={str(UUID(x.strip())) for x in os.getenv("ASSISTANT_SPACES", "").split(",") if x.strip()},
            poll_seconds=int(os.getenv("POLL_SECONDS", "15")),
            schedule_limit=int(os.getenv("SCHEDULE_LIMIT", "1000")),
            sip_domain=os.getenv("SIP_DOMAIN", ""), sip_transport=os.getenv("SIP_TRANSPORT", "udp"),
            upload_url=os.getenv("APP_UPLOAD_URL", ""), upload_key=os.getenv("APP_API_KEY", ""),
            upload_ca=os.getenv("APP_CA_FILE", ""), upload_contract=os.getenv("APP_CONTRACT", "gateway"),
            allow_http=os.getenv("APP_ALLOW_HTTP", "false").lower() == "true",
            upload_idempotent=os.getenv("APP_IDEMPOTENT", "false").lower() == "true")

    def validate(self, cms):
        if self.poll_seconds < 2 or not 1 <= self.schedule_limit <= 10000:
            raise ValueError("Invalid polling interval or schedule limit")
        if self.sip_transport not in ("udp", "tcp", "tls"):
            raise ValueError("SIP_TRANSPORT must be udp, tcp or tls")
        if self.upload_contract not in ("gateway", "protocol-ai"):
            raise ValueError("APP_CONTRACT must be gateway or protocol-ai")
        if not self.enabled:
            return
        if not cms.cms_url or not cms.scheduler_url:
            raise ValueError("Set CMS_URL and CMS_SCHEDULER_URL")
        if not self.notified or not self.spaces:
            raise ValueError("Set PARTICIPANTS_NOTIFIED=true and ASSISTANT_SPACES for approved meetings")
        if not os.getenv("SIP_ID_URI"):
            raise ValueError("Set SIP_ID_URI")
        url = urlsplit(self.upload_url)
        if (not url.hostname or url.username or url.password or url.query or url.fragment or
                (url.scheme != "https" and not (url.scheme == "http" and self.allow_http))):
            raise ValueError("Set APP_UPLOAD_URL to HTTPS; isolated HTTP requires APP_ALLOW_HTTP=true")
