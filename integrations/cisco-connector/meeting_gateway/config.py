import os
import ssl
from dataclasses import dataclass, field
from urllib.parse import urlsplit


@dataclass
class GatewaySettings:
    api_key: str = field(default="", repr=False)
    cms_url: str = ""
    cms_user: str = ""
    cms_password: str = field(default="", repr=False)
    cms_ca_file: str = ""
    cms_bot_uri: str = ""
    scheduler_url: str = ""
    scheduler_user: str = ""
    scheduler_password: str = field(default="", repr=False)

    @classmethod
    def from_env(cls):
        return cls(
            api_key=os.getenv("GATEWAY_API_KEY", ""),
            cms_url=os.getenv("CMS_URL", "").rstrip("/"),
            cms_user=os.getenv("CMS_USERNAME", ""),
            cms_password=os.getenv("CMS_PASSWORD", ""),
            cms_ca_file=os.getenv("CMS_CA_FILE", ""),
            cms_bot_uri=os.getenv("CMS_BOT_SIP_URI", ""),
            scheduler_url=os.getenv("CMS_SCHEDULER_URL", "").rstrip("/"),
            scheduler_user=os.getenv("CMS_SCHEDULER_USERNAME", ""),
            scheduler_password=os.getenv("CMS_SCHEDULER_PASSWORD", ""),
        )

    def validate(self):
        if len(self.api_key) < 32:
            raise ValueError("Set GATEWAY_API_KEY to a random secret of at least 32 characters")
        if self.cms_url:
            url = urlsplit(self.cms_url)
            if (url.scheme != "https" or not url.hostname or url.username or url.password
                    or url.query or url.fragment or url.path not in ("", "/")):
                raise ValueError("CMS_URL must be an HTTPS origin, e.g. https://cms.internal:445")
            if not self.cms_user or not self.cms_password:
                raise ValueError("CMS_USERNAME and CMS_PASSWORD are required with CMS_URL")
        if self.scheduler_url:
            url = urlsplit(self.scheduler_url)
            if (url.scheme != "https" or not url.hostname or url.username or url.password
                    or url.query or url.fragment or url.path not in ("", "/")):
                raise ValueError("CMS_SCHEDULER_URL must be an HTTPS origin")
            if bool(self.scheduler_user) != bool(self.scheduler_password):
                raise ValueError("Set both Scheduler username and password, or neither")

    def cms_tls(self):
        return ssl.create_default_context(cafile=self.cms_ca_file or None)
