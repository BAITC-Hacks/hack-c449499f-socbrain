import secrets
import uuid
import json
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

import httpx
from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, StrictBool

from .config import GatewaySettings
from .providers import CMSClient, ProviderError
from .scheduler import SchedulerClient
from .automation_config import AutomationSettings
from .jobs import Jobs

KEY = APIKeyHeader(name="X-API-Key", auto_error=False)


class Consent(BaseModel):
    participants_notified: StrictBool


class StreamCommand(Consent):
    enabled: StrictBool


def require_notice(notified: bool):
    if not notified:
        raise HTTPException(400, "Уведомите участников о записи и ИИ-транскрибации")


def create_app(config=None, cms_transport=None, automation_config=None):
    config = config or GatewaySettings.from_env()
    automation_config = automation_config or AutomationSettings.from_env()

    @asynccontextmanager
    async def lifespan(app):
        config.validate()
        app.state.jobs = Jobs(automation_config.data_dir)
        with httpx.Client(verify=config.cms_tls(), timeout=20, follow_redirects=False,
                          trust_env=False, transport=cms_transport) as cms_http:
            app.state.cms = CMSClient(config, cms_http)
            app.state.scheduler = SchedulerClient(config, cms_http)
            yield

    app = FastAPI(title="Cisco CMS Connector", version="0.4.0", lifespan=lifespan,
                  description="Cisco CMS control, Scheduler calendar and SIP assistant job status. The assistant runs as a separate worker.")

    def authorize(key: str | None = Depends(KEY)):
        if not key or not secrets.compare_digest(key.encode(), config.api_key.encode()):
            raise HTTPException(401, "Invalid API key")

    secured = [Depends(authorize)]

    @app.exception_handler(ProviderError)
    async def provider_error(_, exc):
        return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})

    @app.exception_handler(httpx.RequestError)
    async def network_error(_, exc):
        code = 504 if isinstance(exc, httpx.TimeoutException) else 502
        return JSONResponse(status_code=code, content={"detail": "Provider connection failed; check network and TLS"})

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/integrations", dependencies=secured)
    def integrations():
        return {"cms": {"configured": bool(config.cms_url)},
                "scheduler": {"configured": bool(config.scheduler_url)},
                "assistant": {"enabled": automation_config.enabled},
                "note": "Configuration status does not verify provider connectivity"}

    @app.get("/api/cms/schedule", dependencies=secured)
    def cms_schedule(hours: int = Query(24, ge=1, le=168)):
        now = datetime.now(timezone.utc)
        return app.state.scheduler.meetings(now, now + timedelta(hours=hours), automation_config.schedule_limit)

    @app.get("/api/assistant/jobs", dependencies=secured)
    def assistant_jobs(limit: int = Query(100, ge=1, le=1000)):
        return app.state.jobs.all(limit)

    @app.get("/api/assistant/status", dependencies=secured)
    def assistant_status():
        try:
            result = json.loads((automation_config.data_dir / "worker.json").read_text(encoding="utf-8"))
            heartbeat = datetime.fromisoformat(result["heartbeat"].replace("Z", "+00:00"))
            result["stale"] = (datetime.now(timezone.utc) - heartbeat).total_seconds() > max(120, automation_config.poll_seconds * 3)
            return result
        except (OSError, ValueError, KeyError):
            return {"enabled": automation_config.enabled, "stale": True, "note": "No worker heartbeat"}

    @app.get("/api/cms/connection", dependencies=secured)
    def cms_connection():
        return app.state.cms.connection_report()

    @app.get("/api/cms/spaces", dependencies=secured)
    def cms_spaces(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
        return app.state.cms.request("GET", "coSpaces", params={"offset": offset, "limit": limit}, expected_root="coSpaces")

    @app.get("/api/cms/spaces/{space_id}", dependencies=secured)
    def cms_space(space_id: uuid.UUID):
        return app.state.cms.request("GET", f"coSpaces/{space_id}", expected_root="coSpace")

    @app.get("/api/cms/alarms", dependencies=secured)
    def cms_alarms(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
        return app.state.cms.request("GET", "system/alarms", params={"offset": offset, "limit": limit})

    @app.get("/api/cms/calls", dependencies=secured)
    def cms_calls(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
        return app.state.cms.request("GET", "calls", params={"offset": offset, "limit": limit}, expected_root="calls")

    @app.get("/api/cms/calls/{call_id}", dependencies=secured)
    def cms_call(call_id: uuid.UUID):
        return app.state.cms.request("GET", f"calls/{call_id}", expected_root="call")

    @app.get("/api/cms/calls/{call_id}/participants", dependencies=secured)
    def cms_participants(call_id: uuid.UUID, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
        return app.state.cms.request("GET", f"calls/{call_id}/participants", params={"offset": offset, "limit": limit})

    @app.post("/api/cms/calls/{call_id}/bot", dependencies=secured, status_code=202)
    def cms_invite(call_id: uuid.UUID, body: Consent):
        require_notice(body.participants_notified)
        if not config.cms_bot_uri:
            raise HTTPException(503, "Configure CMS_BOT_SIP_URI for an existing SIP media client")
        result = app.state.cms.request("POST", f"calls/{call_id}/participants", data={"remoteParty": config.cms_bot_uri})
        return {"status": "invitation_requested", **result}

    @app.put("/api/cms/calls/{call_id}/streaming", dependencies=secured, status_code=202)
    def cms_streaming(call_id: uuid.UUID, body: StreamCommand):
        if body.enabled:
            require_notice(body.participants_notified)
        result = app.state.cms.request("PUT", f"calls/{call_id}", data={"streaming": str(body.enabled).lower()})
        return {"status": "configuration_accepted", "streaming_requested": body.enabled,
                "note": "CMS Streamer and an administrator-configured internal streamUrl are required; verify media at receiver", **result}

    @app.put("/api/cms/calls/{call_id}/recording", dependencies=secured, status_code=202)
    def cms_recording(call_id: uuid.UUID, body: StreamCommand):
        if body.enabled:
            require_notice(body.participants_notified)
        result = app.state.cms.request("PUT", f"calls/{call_id}", data={"recording": str(body.enabled).lower()})
        return {"status": "configuration_accepted", "recording_requested": body.enabled,
                "note": "A configured and licensed CMS Recorder is required. Check recordingStatus on the call; "
                        "this endpoint does not download a recording file.", **result}

    return app


app = create_app()
