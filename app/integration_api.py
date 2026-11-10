"""Use separate read-only API credentials. They never grant dashboard administrator access."""
import hmac
import os
import re
from config_store import setting


def read_only_service_enabled():
    value = os.environ.get("READ_ONLY_API_SERVICE", "false").strip().lower()
    if value not in ("true", "false"):
        raise RuntimeError("READ_ONLY_API_SERVICE must be true or false")
    return value == "true"


def authorize_summary(authorization):
    """Return an HTTP error, or None when authorized. A missing or invalid token disables the API."""
    token = setting("INTEGRATION_API_TOKEN")
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", token):
        return {"status": "disabled"}, 404
    match = re.fullmatch(r"(?i:Bearer) ([A-Za-z0-9_-]{32,256})", authorization or "")
    if not match or not hmac.compare_digest(match.group(1), token):
        return {"status": "unauthorized"}, 401, {"WWW-Authenticate": "Bearer"}
    return None
