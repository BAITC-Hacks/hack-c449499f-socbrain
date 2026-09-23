"""Single-worker Scheduler -> SIP recorder -> application upload pipeline."""
from datetime import datetime, timedelta, timezone
import json
import logging
import re
import signal
import ssl
import subprocess
import sys
import threading

import httpx

from .automation_config import AutomationSettings
from .config import GatewaySettings
from .jobs import Jobs
from .providers import CMSClient, ProviderError
from .scheduler import SchedulerClient, occurrence, utc_text

log = logging.getLogger("cisco-assistant")


def destination(cms, event, config):
    reply = cms.request("GET", "coSpaces/" + event["space"], expected_root="coSpace")
    space = reply["data"]["coSpace"]
    uri = space.get("uri", [""])[0] if isinstance(space, dict) else ""
    uri = re.sub(r"^sips?:", "", uri)
    if "@" not in uri and config.sip_domain:
        uri += "@" + config.sip_domain
    if not re.fullmatch(r"[A-Za-z0-9_.!~*'()%+\-]+@[A-Za-z0-9.\-]+(?::[0-9]{1,5})?", uri):
        raise ProviderError("coSpace has no supported SIP URI; configure SIP_DOMAIN or routing")
    return ("sips:" if config.sip_transport == "tls" else "sip:") + uri + (
        ";transport=tcp" if config.sip_transport == "tcp" else "")


class Engine:
    def __init__(self, config, cms, scheduler, uploader, jobs, spawn=None):
        self.config, self.cms, self.scheduler, self.uploader, self.jobs = config, cms, scheduler, uploader, jobs
        self.spawn = spawn or subprocess.Popen
        self.active = None
        self.last_poll = None
        self.last_error = None

    def publish_status(self):
        target = self.jobs.directory / "worker.json"
        temp = target.with_suffix(".tmp")
        temp.write_text(json.dumps({"heartbeat": utc_text(datetime.now(timezone.utc)),
            "enabled": self.config.enabled, "last_schedule_poll": self.last_poll,
            "last_error": self.last_error, "active_job": self.active[0]["id"] if self.active else None}), encoding="utf-8")
        temp.replace(target)

    def tick(self, now):
        # A finished child is finalized before another meeting can claim the single SIP port.
        self.finish()
        try:
            raw = self.scheduler.meetings(now, now + timedelta(hours=24), self.config.schedule_limit)
            events = []
            for entry in raw:
                if entry.get("coSpace") not in self.config.spaces:
                    continue
                events.append(occurrence(entry))
            self.jobs.sync(events)
            self.last_poll, self.last_error = utc_text(now), None
        except (ProviderError, httpx.RequestError, ValueError, KeyError, TypeError):
            self.last_error = "Schedule unavailable or invalid; no new joins on this cycle"
            self.publish_status()
            self.deliver()
            return
        by_id = {event["id"]: event for event in events}
        if self.active:
            event, process = self.active
            current = by_id.get(event["id"])
            if (current is None or datetime.fromisoformat(current["end"].replace("Z", "+00:00")) <= now
                    or datetime.fromisoformat(current["start"].replace("Z", "+00:00")) > now):
                process.terminate()  # Hang up only this assistant, never the conference.
        for row in sorted(self.jobs.all(10000), key=lambda r: r["event"]["start"]):
            event = row["event"]
            if row["status"] != "pending" or event["id"] not in by_id:
                continue
            start = datetime.fromisoformat(event["start"].replace("Z", "+00:00"))
            end = datetime.fromisoformat(event["end"].replace("Z", "+00:00"))
            if end <= now:
                self.jobs.set(event["id"], "missed", "Meeting ended before joining")
            elif start <= now:
                if self.active:
                    self.jobs.set(event["id"], "skipped", "One assistant supports one meeting at a time")
                    continue
                try:
                    uri = destination(self.cms, event, self.config)
                    path = self.jobs.directory / (event["id"] + ".wav")
                    self.jobs.set(event["id"], "recording")
                    process = self.spawn([sys.executable, "-m", "meeting_gateway.sip_record",
                        "--uri", uri, "--output", str(path), "--seconds", str(max(1, int((end-now).total_seconds())))],
                        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    self.active = event, process
                except (ProviderError, httpx.RequestError, OSError):
                    self.jobs.set(event["id"], "failed", "Could not start SIP recorder; check routing and configuration")
        self.deliver()
        self.publish_status()

    def finish(self):
        if not self.active or self.active[1].poll() is None:
            return
        event, process = self.active
        self.active = None
        path = self.jobs.directory / (event["id"] + ".wav")
        try:
            result = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
            success = process.returncode == 0 and result.get("success") is True and path.stat().st_size > 44
        except (ValueError, OSError):
            success = False
        self.jobs.set(event["id"], "recorded" if success else "failed",
                      "" if success else "No confirmed SIP audio or recording interrupted; inspect local file")

    def deliver(self):
        for row in self.jobs.all(10000):
            if row["status"] != "recorded":
                continue
            event = row["event"]
            path = self.jobs.directory / (event["id"] + ".wav")
            data = {"title": event["title"], "meeting_date": event["meeting_date"]}
            if self.config.upload_contract == "gateway":
                data.update(participants_notified="true", source="cms")
            else:
                data.update(consent="true")
            headers = {"Idempotency-Key": event["id"]}
            if self.config.upload_key:
                headers["X-API-Key"] = self.config.upload_key
            self.jobs.set(event["id"], "uploading")
            try:
                with path.open("rb") as audio:
                    response = self.uploader.post(self.config.upload_url, data=data, headers=headers,
                        files={"file": (path.name, audio, "audio/wav")})
                if not 200 <= response.status_code < 300:
                    retry = self.config.upload_idempotent and (response.status_code >= 500 or response.status_code == 429)
                    self.jobs.set(event["id"], "recorded" if retry else "delivery_unknown",
                                  "Receiver temporarily unavailable; will retry" if retry else "Receiver returned an error; verify before retry")
                    continue
                result = response.json()
                if not isinstance(result, dict) or not isinstance(result.get("id"), str):
                    raise ValueError("No application recording ID")
                self.jobs.set(event["id"], "delivered", result={"id": result["id"]})
            except httpx.ConnectError:
                # No request reached the server. Safe to retry on the next poll.
                self.jobs.set(event["id"], "recorded", "Receiver connection failed; will retry")
            except (httpx.RequestError, ValueError):
                self.jobs.set(event["id"], "recorded" if self.config.upload_idempotent else "delivery_unknown",
                              "Will retry using idempotency key" if self.config.upload_idempotent else "Delivery uncertain; verify receiver before retry")
            except OSError:
                self.jobs.set(event["id"], "failed", "Local recording unavailable")

    def close(self):
        if self.active:
            process = self.active[1]
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            self.finish()


def main():
    import fcntl  # Worker image is Linux; prevents duplicate worker processes sharing the volume.
    logging.basicConfig(level=logging.INFO)
    cms_config, config = GatewaySettings.from_env(), AutomationSettings.from_env()
    cms_config.validate()
    config.validate(cms_config)
    jobs = Jobs(config.data_dir)
    with (config.data_dir / "worker.lock").open("w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        jobs.recover(idempotent=config.upload_idempotent)
        stop = threading.Event()
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        tls = ssl.create_default_context(cafile=config.upload_ca or None)
        with httpx.Client(verify=cms_config.cms_tls(), timeout=20, follow_redirects=False, trust_env=False) as cms_http, \
             httpx.Client(verify=tls, timeout=httpx.Timeout(300, connect=10), follow_redirects=False, trust_env=False) as uploader:
            engine = Engine(config, CMSClient(cms_config, cms_http), SchedulerClient(cms_config, cms_http), uploader, jobs)
            try:
                while not stop.is_set():
                    if config.enabled:
                        engine.tick(datetime.now(timezone.utc))
                    else:
                        engine.publish_status()
                    stop.wait(config.poll_seconds)
            finally:
                engine.close()


if __name__ == "__main__":
    main()
