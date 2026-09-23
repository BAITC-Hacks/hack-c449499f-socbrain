import os
from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1]
content = (root / ".env.ingest.example").read_text(encoding="utf-8")
content = content.replace("SOCBRAIN_API_KEY=", "SOCBRAIN_API_KEY=" + secrets.token_urlsafe(32), 1)
try:
    descriptor = os.open(root / ".env.ingest", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
except FileExistsError:
    print(".env.ingest already exists; left unchanged.")
else:
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
        output.write(content)
    print("Created .env.ingest. Copy SOCBRAIN_API_KEY to APP_API_KEY in the connector configuration locally.")
