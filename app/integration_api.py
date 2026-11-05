"""Dedicated read-only integration credentials; never dashboard privileges."""
import hmac
import os
import re


def read_only_service_enabled():
    value = os.environ.get("READ_ONLY_API_SERVICE", "false").strip().lower()
    if value not in ("true", "false"):
        raise RuntimeError("READ_ONLY_API_SERVICE must be true or false")
    return value == "true"


def authorize_summary(authorization):
    """Return an HTTP error or None; absence/invalid configuration disables API."""
    token = os.environ.get("INTEGRATION_API_TOKEN", "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", token):
        return {"status": "disabled"}, 404
    match = re.fullmatch(r"(?i:Bearer) ([A-Za-z0-9_-]{32,256})", authorization or "")
    if not match or not hmac.compare_digest(match.group(1), token):
        return {"status": "unauthorized"}, 401, {"WWW-Authenticate": "Bearer"}
    return None
