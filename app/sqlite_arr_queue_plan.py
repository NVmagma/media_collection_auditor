"""Validated request-to-queue mapping; no service calls or state writes."""
from app.sqlite_arr_reconciliation import validate_arr_sync_details
from app.sqlite_title_identity import validate_title_folder


def planned_arr_queue_entry(*, request, media_key, title_folder, destination_stage):
    validate_title_folder(title_folder)
    validate_arr_sync_details(request)
    if set(request) != {"service", "title_id", "root", "monitored"}:
        raise ValueError("Only non-secret Arr request fields are accepted")
    key = title_folder if request["service"] == "radarr" else "TV/" + title_folder
    if media_key != key or destination_stage not in ("holding", "keep", "removal"):
        raise ValueError("Arr queue title identity or destination mismatch")
    return {"stage": destination_stage, **request}
