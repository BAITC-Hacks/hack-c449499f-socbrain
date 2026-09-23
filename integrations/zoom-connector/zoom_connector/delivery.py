import ssl

import httpx


class DeliveryError(RuntimeError):
    pass


class Delivery:
    def __init__(self, settings, client=None):
        self.settings = settings
        if client is None:
            tls = ssl.create_default_context(cafile=settings.app_ca_file or None)
            client = httpx.Client(verify=tls, timeout=httpx.Timeout(600, connect=10),
                                  follow_redirects=False, trust_env=False)
        self.client = client

    def close(self):
        self.client.close()

    def upload(self, path, title, meeting_date, key, source="zoom"):
        with path.open("rb") as audio:
            response = self.client.post(self.settings.app_upload_url,
                headers={"X-API-Key": self.settings.app_api_key, "Idempotency-Key": key},
                data={"title": title, "meeting_date": meeting_date,
                      "participants_notified": "true", "source": source},
                files={"file": (path.name, audio, "audio/wav" if path.suffix == ".wav" else "application/octet-stream")})
        if not 200 <= response.status_code < 300:
            raise DeliveryError(f"SOCBrain receiver returned HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError:
            raise DeliveryError("SOCBrain receiver returned invalid JSON") from None
        if not isinstance(data, dict) or not isinstance(data.get("id"), str):
            raise DeliveryError("SOCBrain receiver returned no recording ID")
        return {"id": data["id"]}
