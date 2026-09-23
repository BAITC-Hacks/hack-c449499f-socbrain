"""Documented CMS REST calls. No browser automation or cloud AI."""
from urllib.parse import urlsplit
from xml.etree.ElementTree import ParseError

import httpx
from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException

from .config import GatewaySettings


class ProviderError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def check(response: httpx.Response):
    if 200 <= response.status_code < 300:
        return
    status = response.status_code
    if status == 404:
        raise ProviderError("CMS API resource was not found", 404)
    if status == 429:
        raise ProviderError("Provider rate limit reached; retry later", 429)
    if status in (401, 403):
        raise ProviderError("Provider denied access; check credentials, permissions and policies")
    # Never leak provider response bodies, URLs, credentials or meeting data in errors.
    raise ProviderError(f"Provider returned HTTP {status}")


def xml_node(node):
    result = {"@" + k: v for k, v in node.attrib.items()}
    for child in node:
        name = child.tag.split("}")[-1]
        result.setdefault(name, []).append(xml_node(child))
    if not result:
        return node.text or ""
    return result


class CMSClient:
    def __init__(self, config: GatewaySettings, client: httpx.Client):
        self.config, self.client = config, client

    def request(self, method, resource, *, params=None, data=None, expected_root=None):
        if not self.config.cms_url:
            raise ProviderError("Cisco CMS is not configured", 503)
        response = self.client.request(
            method, self.config.cms_url + "/api/v1/" + resource,
            auth=(self.config.cms_user, self.config.cms_password),
            params=params, data=data, headers={"Accept": "application/xml"},
        )
        check(response)
        payload = None
        if response.content:
            try:
                root = ElementTree.fromstring(response.content, forbid_dtd=True)
                payload = {root.tag.split("}")[-1]: xml_node(root)}
            except (ParseError, DefusedXmlException):
                raise ProviderError("CMS returned invalid or unsafe XML") from None
        if expected_root and (not payload or expected_root not in payload):
            raise ProviderError("CMS returned an unexpected XML document")
        # Location may be absolute. Return only its path; never use it for outgoing requests.
        location = urlsplit(response.headers.get("location", "")).path or None
        return {"data": payload, "resource": location}

    def connection_report(self):
        status = self.request("GET", "system/status", expected_root="status")
        values = status["data"]["status"]
        versions = values.get("softwareVersion", []) if isinstance(values, dict) else []
        if not versions or not isinstance(versions[0], str) or not versions[0].strip():
            raise ProviderError("CMS status did not include a software version")
        diagnostics = {}
        for name, resource, params in (
            ("instance_licensing", "system/licensing", None),
            ("cluster_licensing", "clusterLicensing", None),
            ("alarms", "system/alarms", {"offset": 0, "limit": 100}),
        ):
            try:
                result = self.request("GET", resource, params=params)
                if not result["data"]:
                    raise ProviderError("CMS returned an empty diagnostic document")
                diagnostics[name] = {"status": "available", **result}
            except ProviderError as exc:
                diagnostics[name] = {"status": "unavailable", "code": exc.status_code, "detail": str(exc)}
            except httpx.RequestError:
                diagnostics[name] = {"status": "unavailable", "detail": "CMS diagnostic connection failed"}
        return {"api_connected": True, "software_version": versions[0], "system": status,
                "diagnostics": diagnostics, "media_ready": "unknown",
                "note": "Read-only check. License data and the first 100 alarms do not prove media availability; "
                        "verify Recorder/Streamer or a SIP receiver separately."}
