"""Non-authorizing production readiness report."""

from app.sqlite_readiness import inspect_sqlite_readiness


def inspect_production_integration(backend, source_json, backup_json, database):
    """Inspect migration artifacts without enabling SQLite or moving media."""
    isolated = inspect_sqlite_readiness(source_json, backup_json, database)
    blockers = list(isolated["blockers"])
    if backend != "json":
        blockers.append("unsupported_production_backend")
    blockers.append("trusted_move_recovery_not_implemented")
    return {
        "production_activation": "disabled",
        "storage_authority": "json",
        "authorization": "not_authorized",
        "ready_for_production": False,
        "ready_for_isolated_review": isolated["ready_for_isolated_review"],
        "blockers": blockers,
    }
