"""Opt-in, read-only Flask blueprint for experimental recovery status.

Not registered by the production dashboard. The host application must
authenticate an administrator before this blueprint is reachable; a separate
guard is required here as defense in depth.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from flask import Blueprint, jsonify, request

from app.sqlite_recovery_report import inspect_pending_recovery_status


def create_recovery_status_blueprint(
    database: str | Path,
    *,
    is_admin: Callable[[], bool],
) -> Blueprint:
    """Create an isolated endpoint without activating it on production."""
    if not callable(is_admin):
        raise TypeError("An administrator authorization callback is required")
    database = Path(database)
    blueprint = Blueprint("experimental_sqlite_recovery", __name__)

    @blueprint.get("/api/experimental/sqlite/recovery-status")
    def recovery_status():
        # Never infer admin privileges from a query parameter or cookie.
        try:
            authorized = is_admin() is True
        except Exception:
            authorized = False
        if not authorized:
            return jsonify({"ok": False, "reason": "forbidden"}), 403
        if not database.is_file():
            return jsonify({"ok": False, "reason": "database_unavailable"}), 503
        try:
            report = inspect_pending_recovery_status(database)
        except Exception:
            # Never expose exception strings, paths, or credentials over HTTP.
            return jsonify({"ok": False, "reason": "inspection_failed"}), 503
        response = jsonify({"ok": True, **report})
        response.headers["Cache-Control"] = "no-store"
        return response

    return blueprint
