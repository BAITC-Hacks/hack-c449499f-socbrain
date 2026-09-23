from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs

import httpx
import pytest
from fastapi.testclient import TestClient

from meeting_gateway.api import create_app
from meeting_gateway.automation import Engine, destination
from meeting_gateway.automation_config import AutomationSettings
from meeting_gateway.config import GatewaySettings
from meeting_gateway.jobs import Jobs
from meeting_gateway.providers import CMSClient, ProviderError
from meeting_gateway.scheduler import SchedulerClient, occurrence

SPACE = "a02820a8-09b6-4cd0-b8fa-af94626943d0"
MEETING = "45c5e97d-c913-4d0e-90a3-f648a7d726c0"
KEY = "test-only-" + "x" * 32
AUTH = {"X-API-Key": KEY}
NOW = datetime(2026, 9, 23, 10, 0, tzinfo=timezone.utc)


@pytest.fixture
def config():
    return GatewaySettings(api_key=KEY, cms_url="https://cms.test:445", cms_user="user", cms_password="SECRET",
                           scheduler_url="https://scheduler.test:8443", cms_bot_uri="bot@test")


@pytest.fixture
def auto(tmp_path):
    return AutomationSettings(data_dir=tmp_path, spaces={SPACE}, sip_domain="cms.test",
                              upload_url="https://app.test/api/recordings", upload_key="app-secret")


def event(**kwargs):
    return {"coSpace": SPACE, "meeting": MEETING, "summary": "Совещание", "dtStart": "2026-09-23T15:00:00",
            "dtEnd": "2026-09-23T16:00:00", "timeZone": "Asia/Qyzylorda", **kwargs}


def test_scheduler_uses_separate_origin_json_and_utc(config):
    def respond(request):
        assert request.url.host == "scheduler.test"
        assert request.url.path == "/api/v1/scheduler/meetings"
        assert request.url.params["fromTime"] == "2026-09-23T10:00:00Z"
        assert "authorization" not in request.headers  # CMS credentials must not cross to another origin.
        return httpx.Response(200, json=[event()])
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        assert len(SchedulerClient(config, client).meetings(NOW, NOW + timedelta(days=1))) == 1


@pytest.mark.parametrize("payload", [{"error": "bad"}, ["bad"], [event(), event()]])
def test_bad_or_truncated_schedule_is_rejected(config, payload):
    with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=payload))) as client:
        with pytest.raises(ProviderError):
            SchedulerClient(config, client).meetings(NOW, NOW + timedelta(days=1), limit=2)


def test_timezone_and_recurrence_identity():
    first = occurrence(event(recurrence="2026-09-23T15:00:00"))
    assert first["start"] == "2026-09-23T10:00:00Z"
    assert first["meeting_date"] == "2026-09-23"
    assert first["id"] == occurrence(event(recurrence="2026-09-23T15:00:00", summary="Edited"))["id"]
    assert first["id"] != occurrence(event(recurrence="2026-09-24T15:00:00"))["id"]


@pytest.mark.parametrize("changes", [dict(isFullDayMeeting=True), dict(dtEnd="2026-09-23T14:00:00"),
    dict(timeZone="Europe/Berlin", dtStart="2026-10-25T02:30:00", dtEnd="2026-10-25T03:30:00"),
    dict(timeZone="Europe/Berlin", dtStart="2026-03-29T02:30:00", dtEnd="2026-03-29T03:30:00")])
def test_unsafe_time_is_rejected(changes):
    with pytest.raises(ValueError):
        occurrence(event(**changes))


def test_api_auth_controls_and_no_core_app_dependency(config, auto):
    seen = []
    def respond(request):
        seen.append(request)
        if request.method == "PUT":
            assert parse_qs(request.content.decode()) == {"recording": ["true"]}
            return httpx.Response(200)
        return httpx.Response(200, text='<coSpaces total="0"/>')
    with TestClient(create_app(config, httpx.MockTransport(respond), auto)) as api:
        assert api.get("/health").status_code == 200
        for route in ["/api/cms/spaces", "/api/cms/schedule", "/api/assistant/jobs", "/api/assistant/status"]:
            assert api.get(route).status_code == 401
        assert not seen
        assert api.get("/api/cms/spaces", headers=AUTH).status_code == 200
        assert api.get("/api/assistant/status", headers=AUTH).json()["stale"] is True
        path = f"/api/cms/calls/{MEETING}/recording"
        assert api.put(path, headers=AUTH, json={"enabled": True, "participants_notified": False}).status_code == 400
        assert api.put(path, headers=AUTH, json={"enabled": True, "participants_notified": True}).status_code == 202
        assert "/api/recordings" not in api.get("/openapi.json").json()["paths"]


@pytest.mark.parametrize("xml", ["<html/>", '<!DOCTYPE x [<!ENTITY y "x">]><calls>&y;</calls>', "bad"])
def test_invalid_cms_xml(config, auto, xml):
    with TestClient(create_app(config, httpx.MockTransport(lambda r: httpx.Response(200, text=xml)), auto)) as api:
        assert api.get("/api/cms/calls", headers=AUTH).status_code == 502


@pytest.mark.parametrize("status", [401, 403, 302, 500])
def test_cms_errors_do_not_leak_secret(config, auto, status):
    with TestClient(create_app(config, httpx.MockTransport(lambda r: httpx.Response(status, text="SECRET")), auto)) as api:
        response = api.get("/api/cms/calls", headers=AUTH)
        assert response.status_code == 502
        assert "SECRET" not in response.text


def make_engine(config, auto, response=None):
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text="<coSpace><uri>room</uri></coSpace>")))
    cms = CMSClient(config, client)
    schedules = [event()]
    scheduler = SimpleNamespace(meetings=lambda *args: schedules)
    uploads = []
    def upload(request):
        uploads.append(request)
        return response(request) if response else httpx.Response(201, json={"id": "app-recording"})
    uploader = httpx.Client(transport=httpx.MockTransport(upload))
    processes = []
    def spawn(args, **kwargs):
        process = SimpleNamespace(returncode=None, terminated=False)
        process.poll = lambda: process.returncode
        process.terminate = lambda: setattr(process, "terminated", True)
        processes.append((args, process))
        return process
    return Engine(auto, cms, scheduler, uploader, Jobs(auto.data_dir), spawn), schedules, processes, uploads


def finish(engine, process, success=True):
    item = engine.active[0]
    path = engine.jobs.directory / (item["id"] + ".wav")
    path.write_bytes(b"x" * 100)
    path.with_suffix(".json").write_text(json.dumps({"success": success}))
    process.returncode = 0 if success else 1


def test_pipeline_joins_once_uploads_closed_file_and_survives_restart(config, auto):
    engine, schedules, processes, uploads = make_engine(config, auto)
    engine.tick(NOW)
    engine.tick(NOW + timedelta(seconds=15))
    assert len(processes) == 1 and not uploads
    assert "sip:room@cms.test" in processes[0][0]
    finish(engine, processes[0][1])
    engine.tick(NOW + timedelta(seconds=30))
    assert len(uploads) == 1
    assert b'participants_notified' in uploads[0].content
    assert engine.jobs.all()[0]["status"] == "delivered"
    restarted, _, _, again = make_engine(config, auto)
    restarted.jobs.recover()
    restarted.tick(NOW + timedelta(seconds=45))
    assert not again and restarted.active is None


def test_cancelled_meeting_stops_only_assistant(config, auto):
    engine, schedules, processes, _ = make_engine(config, auto)
    engine.tick(NOW)
    schedules.clear()
    engine.tick(NOW + timedelta(seconds=15))
    assert processes[0][1].terminated


def test_bad_calendar_does_not_join_cached_meetings(config, auto):
    engine, _, processes, _ = make_engine(config, auto)
    engine.tick(NOW - timedelta(minutes=1))
    engine.scheduler.meetings = lambda *args: [event(dtEnd="broken")]
    engine.tick(NOW)
    assert not processes
    assert engine.last_error


def test_overlap_and_allowlist(config, auto):
    engine, schedules, processes, _ = make_engine(config, auto)
    schedules.append(event(meeting="38f91366-7dfc-4a51-af28-466d01010d1f"))
    schedules.append(event(coSpace="0094dc22-a8c0-45f3-8ba8-a4c1a159c83e"))
    engine.tick(NOW)
    assert len(processes) == 1
    assert sorted(row["status"] for row in engine.jobs.all()) == ["recording", "skipped"]


def test_failed_audio_never_uploaded(config, auto):
    engine, _, processes, uploads = make_engine(config, auto)
    engine.tick(NOW)
    finish(engine, processes[0][1], success=False)
    engine.tick(NOW + timedelta(seconds=15))
    assert not uploads and engine.jobs.all()[0]["status"] == "failed"


def test_uncertain_upload_is_not_automatically_retried(config, auto):
    def timeout(request):
        raise httpx.ReadTimeout("SECRET", request=request)
    engine, _, processes, uploads = make_engine(config, auto, timeout)
    engine.tick(NOW)
    finish(engine, processes[0][1])
    engine.tick(NOW + timedelta(seconds=15))
    engine.tick(NOW + timedelta(seconds=30))
    assert len(uploads) == 1
    assert engine.jobs.all()[0]["status"] == "delivery_unknown"


def test_recover_crashed_jobs(auto):
    jobs = Jobs(auto.data_dir)
    e = occurrence(event())
    jobs.sync([e])
    jobs.set(e["id"], "recording")
    jobs.recover()
    assert jobs.all()[0]["status"] == "failed"
    jobs.set(e["id"], "uploading")
    jobs.recover()
    assert jobs.all()[0]["status"] == "delivery_unknown"


def test_config_requires_explicit_automation_settings(config, auto, monkeypatch):
    with pytest.raises(ValueError, match="PARTICIPANTS_NOTIFIED"):
        replace(auto, enabled=True).validate(config)
    monkeypatch.setenv("SIP_ID_URI", "sip:assistant@cms.test")
    replace(auto, enabled=True, notified=True).validate(config)
    with pytest.raises(ValueError, match="HTTPS"):
        replace(auto, enabled=True, notified=True, upload_url="http://app.test/upload").validate(config)


def test_idempotent_receiver_allows_retry_with_same_key(config, auto):
    seen = []
    def respond(request):
        seen.append(request.headers["Idempotency-Key"])
        if len(seen) == 1:
            raise httpx.ReadTimeout("response lost", request=request)
        return httpx.Response(201, json={"id": "same-receiver-id"})
    engine, _, processes, _ = make_engine(config, replace(auto, upload_idempotent=True), respond)
    engine.tick(NOW)
    finish(engine, processes[0][1])
    engine.tick(NOW + timedelta(seconds=15))
    assert engine.jobs.all()[0]["status"] == "recorded"
    engine.tick(NOW + timedelta(seconds=30))
    assert len(seen) == 2 and seen[0] == seen[1]
    assert engine.jobs.all()[0]["status"] == "delivered"


def test_cancelled_future_occurrence_can_return_after_reschedule(auto):
    jobs = Jobs(auto.data_dir)
    entry = occurrence(event())
    jobs.sync([entry])
    jobs.sync([])
    assert jobs.all()[0]["status"] == "cancelled"
    jobs.sync([entry])
    assert jobs.all()[0]["status"] == "pending"
