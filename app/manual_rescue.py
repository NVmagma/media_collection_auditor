"""Guarded manual moves out of Removal."""
import datetime
import importlib
import os
from run_control import begin_rescue, end_rescue

def rescue_title(library, title, destination):
    if library not in ("Movies", "TV") or destination not in ("keep", "holding"):
        return False, "Invalid request.", 400
    if not isinstance(title, str) or not title or title in (".", "..") or os.path.basename(title) != title:
        return False, "Invalid folder name.", 400
    if not begin_rescue():
        return False, "Audit or rescue already in progress.", 409
    try:
        auditor = importlib.import_module("collection_auditor")
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
        if auditor.DRY_RUN:
            auditor.record_action("manual_rescue_preview", title, "Removal to " + destination,
                                  library, status="planned")
            return True, "Dry Run preview recorded; no media moved.", 200
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
        auditor.save_state(state)
        auditor.record_action("manual_rescue", title, "Removal to " + destination, library)
        root = lib["app_keep"] if destination == "keep" else lib["app_holding"]
        if not lib["arr"].notify_moved(title, root, destination == "keep"):
            auditor.record_action("arr_sync_failed", title, "Manual rescue moved media but Arr update failed",
                                  library, status="failed")
            return True, "Moved successfully; Radarr/Sonarr sync failed. Check service logs.", 200
        return True, "Moved to " + destination.capitalize() + ".", 200
    except (Exception, SystemExit) as exc:
        return False, "Rescue error: " + str(exc)[:160], 500
    finally:
        end_rescue()
