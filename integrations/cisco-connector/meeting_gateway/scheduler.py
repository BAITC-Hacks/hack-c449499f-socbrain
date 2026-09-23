"""CMS 3.3+ Scheduler API (separate HTTPS listener, JSON rather than XML)."""
from datetime import datetime, timezone
import hashlib
from uuid import UUID
from zoneinfo import ZoneInfo

from .providers import ProviderError, check


def utc_text(value):
    if value.tzinfo is None:
        raise ValueError("A timezone is required")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def occurrence(raw):
    """Scheduler expands recurrences itself; never independently expand rrule."""
    if raw.get("isFullDayMeeting"):
        raise ValueError("All-day meetings require explicit start and end times")
    tz = ZoneInfo(raw.get("timeZone") or "UTC")
    def instant(name):
        value = datetime.fromisoformat(raw[name].replace("Z", "+00:00"))
        if value.tzinfo is None:
            # Reject ambiguous/nonexistent DST times rather than choose the wrong meeting.
            a, b = value.replace(tzinfo=tz, fold=0), value.replace(tzinfo=tz, fold=1)
            if a.utcoffset() != b.utcoffset():
                raise ValueError("Ambiguous or nonexistent local meeting time")
            value = a
        return value.astimezone(timezone.utc)
    start, end = instant("dtStart"), instant("dtEnd")
    if not start < end:
        raise ValueError("Invalid meeting interval")
    meeting, space = str(UUID(raw["meeting"])), str(UUID(raw["coSpace"]))
    identity = meeting + "/" + str(raw.get("recurrence") or utc_text(start))
    return {"id": hashlib.sha256(identity.encode()).hexdigest()[:32], "meeting": meeting,
            "space": space, "start": utc_text(start), "end": utc_text(end),
            "meeting_date": start.astimezone(tz).date().isoformat(),
            "title": str(raw.get("summary") or "Cisco meeting")[:300]}


class SchedulerClient:
    def __init__(self, config, client):
        self.config, self.client = config, client

    def meetings(self, start, end, limit=1000):
        if not self.config.scheduler_url:
            raise ProviderError("CMS Scheduler is not configured", 503)
        auth = ((self.config.scheduler_user, self.config.scheduler_password)
                if self.config.scheduler_user else None)
        response = self.client.get(self.config.scheduler_url + "/api/v1/scheduler/meetings",
            params={"fromTime": utc_text(start), "untilTime": utc_text(end), "maxMeetings": limit},
            auth=auth, headers={"Accept": "application/json"})
        check(response)
        try:
            result = response.json()
        except ValueError:
            raise ProviderError("Scheduler returned invalid JSON") from None
        if not isinstance(result, list) or any(not isinstance(item, dict) for item in result):
            raise ProviderError("Scheduler returned an unexpected document")
        # No offset parameter is documented: refuse an ambiguous truncated snapshot.
        if len(result) >= limit:
            raise ProviderError("Scheduler result reached limit; narrow the time window or raise SCHEDULE_LIMIT")
        return result
