import json
import os
from datetime import datetime, timezone
from pathlib import Path

path = Path(os.getenv("CONNECTOR_DATA_DIR", "/data")) / "worker.json"
try:
    state = json.loads(path.read_text(encoding="utf-8"))
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(state["heartbeat"])).total_seconds()
    raise SystemExit(0 if age < 420 else 1)
except (OSError, ValueError, KeyError):
    raise SystemExit(1)
