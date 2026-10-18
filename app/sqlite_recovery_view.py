"""Optional operator view for experimental SQLite recovery.

This blueprint is not registered in the production Flask application.
The host must explicitly register it with an administrator predicate.
No JavaScript, forms, credentials, or write operations are exposed.
"""

from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Callable

from flask import Blueprint, Response

from app.sqlite_recovery_report import inspect_pending_recovery_status
from app.sqlite_recovery_guidance import explain_recovery_status


def create_recovery_view_blueprint(
    database: str | Path, *, is_admin: Callable[[], bool],
) -> Blueprint:
    if not callable(is_admin):
        raise TypeError("Administrator authorization callback required")
    database = Path(database)
    blueprint = Blueprint("experimental_sqlite_recovery_view", __name__)

    @blueprint.get("/experimental/sqlite/recovery")
    def recovery_view():
        headers = {
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; style-src 'none'; frame-ancestors 'none'",
        }
        try:
            authorized = is_admin() is True
        except Exception:
            authorized = False
        if not authorized:
            return Response("Forbidden", status=403, headers=headers,
                            mimetype="text/plain")
        if not database.is_file():
            return Response("Experimental database unavailable", status=503,
                            headers=headers, mimetype="text/plain")
        try:
            report = inspect_pending_recovery_status(database)
        except Exception:
            return Response("Recovery status unavailable", status=503,
                            headers=headers, mimetype="text/plain")
        fields = (
            ("Status", report["status"]),
            ("Authorization", report["authorization"]),
            ("Storage authority", report["storage_authority"]),
            ("Production activation", report["production_activation"]),
            ("Revision", report["revision"]),
        )
        if report["status"] == "blocked":
            fields += (
                ("Operation", report["operation_id"]),
                ("Kind", report["operation_kind"]),
                ("Phase", report["operation_phase"]),
                ("Blocker", report["blocker"]),
            )
        guidance = explain_recovery_status(report)
        fields += tuple((label, guidance[key]) for label, key in (
            ("Explanation", "summary"), ("Recommended review", "next_step"),
            ("Phase explanation", "phase_explanation"),
        ) if key in guidance)
        rows = "".join(
            "<tr><th scope='row'>" + escape(label) + "</th><td>"
            + escape(str(value)) + "</td></tr>"
            for label, value in fields
        )
        page = (
            "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<title>Experimental recovery status</title></head>"
            "<body><main><h1>Experimental SQLite recovery status</h1>"
            "<p>Read-only diagnostics. Recovery is not authorized. "
            "Production state remains JSON.</p>"
            "<table>" + rows + "</table></main></body></html>"
        )
        return Response(page, status=200, headers=headers, mimetype="text/html")

    return blueprint
