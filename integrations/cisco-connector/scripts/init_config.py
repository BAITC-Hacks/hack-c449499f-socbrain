import os
from pathlib import Path
import secrets

root = Path(__file__).resolve().parents[1]
content = (root / ".env.example").read_text(encoding="utf-8")
content = content.replace("GATEWAY_API_KEY=", "GATEWAY_API_KEY=" + secrets.token_urlsafe(32), 1)
try:
    descriptor = os.open(root / ".env", os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
except FileExistsError:
    print(".env already exists; left unchanged.")
else:
    with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as output:
        output.write(content)
    print("Created .env with a random API key. Fill in Cisco connection values locally.")
