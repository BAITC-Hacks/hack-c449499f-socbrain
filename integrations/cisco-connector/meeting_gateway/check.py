"""Read-only diagnostics from inside the container: python -m meeting_gateway.check."""
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main():
    request = Request("http://127.0.0.1:8010/api/cms/connection",
                      headers={"X-API-Key": os.getenv("GATEWAY_API_KEY", "")})
    try:
        with urlopen(request, timeout=100) as response:
            report = json.load(response)
    except HTTPError as exc:
        print(f"Connection check failed (HTTP {exc.code}). Check CMS configuration, credentials and network.")
        return 1
    except (URLError, TimeoutError, ValueError):
        print("Connector is unavailable or returned an invalid response.")
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if all(item["status"] == "available" for item in report["diagnostics"].values()) else 2


if __name__ == "__main__":
    sys.exit(main())
