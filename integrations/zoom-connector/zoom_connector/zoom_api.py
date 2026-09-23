from datetime import datetime, timedelta, timezone
import threading
from urllib.parse import quote

import httpx


class ZoomError(RuntimeError):
    pass


class ZoomAPI:
    def __init__(self, settings, client=None):
        self.settings = settings
        self.client = client or httpx.Client(timeout=httpx.Timeout(60, connect=10),
                                             follow_redirects=False, trust_env=False)
        self._token = None
        self._expires = datetime.min.replace(tzinfo=timezone.utc)
        self._lock = threading.Lock()

    def close(self):
        self.client.close()

    def token(self):
        with self._lock:
            if self._token and datetime.now(timezone.utc) < self._expires:
                return self._token
            response = self.client.post("https://zoom.us/oauth/token",
                params={"grant_type": "account_credentials", "account_id": self.settings.account_id},
                auth=(self.settings.client_id, self.settings.client_secret))
            if response.status_code != 200:
                raise ZoomError(f"Zoom OAuth failed with HTTP {response.status_code}")
            try:
                data = response.json()
                token, expires = data["access_token"], int(data.get("expires_in", 3600))
            except (ValueError, KeyError, TypeError):
                raise ZoomError("Zoom OAuth returned an invalid document") from None
            self._token = token
            self._expires = datetime.now(timezone.utc) + timedelta(seconds=max(30, expires - 60))
            return token

    def request(self, method, path, **kwargs):
        headers = dict(kwargs.pop("headers", {}))
        headers["Authorization"] = "Bearer " + self.token()
        response = self.client.request(method, "https://api.zoom.us/v2" + path, headers=headers, **kwargs)
        if not 200 <= response.status_code < 300:
            raise ZoomError(f"Zoom API {method} {path.split('?')[0]} failed with HTTP {response.status_code}")
        return response

    def pages(self, path, list_key, params=None):
        params, result, token = dict(params or {}), [], ""
        for _ in range(100):
            query = {**params, "page_size": 100}
            if token:
                query["next_page_token"] = token
            response = self.request("GET", path, params=query)
            try:
                data = response.json()
                items = data.get(list_key, [])
            except ValueError:
                raise ZoomError("Zoom API returned invalid JSON") from None
            if not isinstance(items, list):
                raise ZoomError("Zoom API returned an unexpected document")
            result.extend(x for x in items if isinstance(x, dict))
            token = data.get("next_page_token") or ""
            if not token:
                return result
        raise ZoomError("Zoom API pagination limit reached")

    def calendar(self, user_id):
        encoded = quote(user_id, safe="")
        hosted = self.pages(f"/users/{encoded}/meetings", "meetings", {"type": "upcoming_meetings"})
        invited = self.pages(f"/users/{encoded}/upcoming_meetings", "meetings")
        merged = {}
        for source, rows in (("hosted", hosted), ("invited", invited)):
            for row in rows:
                key = str(row.get("uuid") or row.get("id")) + ":" + str(row.get("occurrence_id") or row.get("start_time") or "")
                if key == "None:":
                    continue
                current = merged.setdefault(key, dict(row))
                sources = set(current.get("calendar_sources", []))
                sources.add(source)
                current["calendar_sources"] = sorted(sources)
        return list(merged.values())

    def start_rtms(self, meeting_id, rtms_client_id):
        return self.request("PATCH", f"/live_meetings/{quote(str(meeting_id), safe='')}/rtms_app/status",
            json={"action": "start", "settings": {"client_id": rtms_client_id}})
