from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1]
target = root / ".env"
if target.exists():
    raise SystemExit(".env already exists; it was not changed")
example = (root / ".env.example").read_text(encoding="utf-8")
example = example.replace("ZOOM_CONNECTOR_API_KEY=\n", "ZOOM_CONNECTOR_API_KEY=" + secrets.token_urlsafe(36) + "\n")
target.write_text(example, encoding="utf-8")
print("Created .env. Fill Zoom and SOCBrain credentials before starting services.")
