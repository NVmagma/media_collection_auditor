"""Guarded manual moves out of Removal."""
import datetime
import importlib
import os
import json
from audit_history import new_record, finish_record
from run_control import begin_rescue, end_rescue
from backend_selection import require_json_backend
from state_lock import audit_run_lock, StateLockBusy

def rescue_title(library, title, destination):
    if library not in ("Movies", "TV") or destination not in ("keep", "holding"):
        return False, "Invalid request.", 400
    if not isinstance(title, str) or not title or title in (".", "..") or os.path.basename(title) != title:
        return False, "Invalid folder name.", 400
    try:
        require_json_backend(os.environ.get("AUDITOR_STATE_BACKEND", "json"))
    except RuntimeError:
        return False, "Manual rescue requires the JSON backend.", 409
    if not begin_rescue():
        return False, "Audit or rescue already in progress.", 409
    try:
        auditor = importlib.import_module("collection_auditor")
        # Import may load dotenv settings; validate the effective selection too.
        try:
            require_json_backend(os.environ.get("AUDITOR_STATE_BACKEND", "json"))
        except RuntimeError:
            return False, "Manual rescue requires the JSON backend.", 409
        state_file, dry_run = auditor.STATE_FILE, auditor.DRY_RUN
        with audit_run_lock(state_file) as verify_lock:
            def verify_binding():
                verify_lock()
                require_json_backend(os.environ.get("AUDITOR_STATE_BACKEND", "json"))
                if auditor.STATE_FILE != state_file or auditor.DRY_RUN is not dry_run:
                    raise RuntimeError("Rescue state configuration changed")
            return _rescue_title_locked(auditor, library, title, destination,
                                        verify_binding, state_file, dry_run)
    except StateLockBusy:
        return False, "Another state operation is in progress.", 409
    except (Exception, SystemExit) as exc:
        return False, "Rescue error: " + str(exc)[:160], 500
    finally:
        end_rescue()


def _rescue_title_locked(auditor, library, title, destination, verify_lock, state_file, dry_run):
    """Hold the cooperating-writer lock from state read through Arr notification."""
    verify_lock()
    libs = {lib["name"]: lib for lib in auditor.build_libraries()}
    if library not in libs:
        return False, "Library is disabled.", 400
    lib = libs[library]
    src_root, dst_root = os.path.realpath(lib["removal"]), os.path.realpath(lib[destination])
    src, dst = os.path.join(src_root, title), os.path.join(dst_root, title)
    if not os.path.isdir(src_root) or not os.path.isdir(dst_root):
        return False, "Configured directory missing.", 409
    if os.path.islink(src) or not os.path.isdir(src) or not auditor.is_within(src, src_root):
        return False, "Title not found or unsafe path.", 404
    if os.path.lexists(dst) or not auditor.is_within(dst, dst_root):
        return False, "Destination exists or is unsafe.", 409
    if os.stat(src_root).st_dev != os.stat(dst_root).st_dev:
        return False, "Cross-filesystem rescues are disabled.", 409
    state = auditor.load_state()
    key = auditor.state_key(lib, title)
    if key not in state["in_removal"]:
        return False, "Title not tracked in Removal.", 409
    if dry_run:
        auditor.record_action("manual_rescue_preview", title, "Removal to " + destination,
                              library, status="planned")
        return True, "Dry Run preview recorded; no media moved.", 200
    verify_lock()
    error = auditor.safe_move_directory(src, dst_root)
    if error:
        return False, "Move failed: " + error, 409
    state["in_removal"].pop(key, None)
    state["queued"].pop(key, None)
    state["first_seen"].pop(key, None)
    now = datetime.datetime.now().isoformat()
    if destination == "holding":
        state["queued"][key] = now
        state["keep_seen"].pop(key, None)
    else:
        state["keep_seen"][key] = now
    # Save state atomically and surface failures rather than swallowing them.
    tmp_file = state_file + ".rescue.tmp"
    os.makedirs(os.path.dirname(state_file), exist_ok=True)
    with open(tmp_file, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    verify_lock()
    os.replace(tmp_file, state_file)
    auditor.record_action("manual_rescue", title, "Removal to " + destination, library)
    history = new_record("manual_rescue", False)
    finish_record(history, "completed", {
        "movies_processed": 1 if library == "Movies" else 0,
        "tv_processed": 1 if library == "TV" else 0,
        "action_counts": {"manual_rescue": 1},
        "status_counts": {"done": 1},
        "actions": [{"library": library, "folder": title, "action": "manual_rescue",
                     "status": "done", "time": history["started_at"]}]
    })
    root = lib["app_keep"] if destination == "keep" else lib["app_holding"]
    verify_lock()
    if not lib["arr"].notify_moved(title, root, destination == "keep"):
        auditor.record_action("arr_sync_failed", title, "Manual rescue moved media but Arr update failed",
                              library, status="failed")
        return True, "Moved successfully; Radarr/Sonarr sync failed. Check service logs.", 200
    return True, "Moved to " + destination.capitalize() + ".", 200
