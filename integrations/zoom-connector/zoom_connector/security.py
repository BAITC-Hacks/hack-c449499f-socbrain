import hashlib
import hmac
import json
import time


def webhook_signature(secret, timestamp, body):
    message = b"v0:" + str(timestamp).encode() + b":" + body
    return "v0=" + hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def verify_webhook(secret, timestamp, signature, body, now=None, tolerance=300):
    try:
        stamp = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs((time.time() if now is None else now) - stamp) > tolerance:
        return False
    expected = webhook_signature(secret, timestamp, body)
    return bool(signature) and hmac.compare_digest(expected, signature)


def validation_response(secret, plain_token):
    encrypted = hmac.new(secret.encode(), plain_token.encode(), hashlib.sha256).hexdigest()
    return {"plainToken": plain_token, "encryptedToken": encrypted}


def json_body(raw):
    try:
        value = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValueError("Invalid JSON") from None
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return value
