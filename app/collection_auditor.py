import os
import json
import time
import shutil
import posixpath
import datetime
from typing import Dict, Any, Optional

import requests
from dotenv import load_dotenv

# ==============================================
# --- CONFIGURATION ---
# ==============================================
load_dotenv()

# Safety first: nothing is moved, deleted, or sent to Radarr unless DRY_RUN=false.
DRY_RUN = os.environ.get("DRY_RUN", "true").strip().lower() != "false"

# Jellyfin (decides favorited / not-at-all)
JELLYFIN_URL = os.environ.get("JELLYFIN_HOST_URL", "http://localhost:8096").rstrip("/")
JELLYFIN_TOKEN = (os.environ.get("JELLYFIN_API_TOKEN") or "").strip().strip("'\"")
DISLIKE_TAG = os.environ.get("DISLIKE_TAG", "not-at-all")  # Jellyfin tag meaning "family hated it"

# Radarr (told about every move / removal)
RADARR_URL = os.environ.get("RADARR_URL", "").rstrip("/")
RADARR_KEY = os.environ.get("RADARR_API_KEY")

# Folders as THIS container sees them
BASE_MEDIA_PATH = os.environ.get("MEDIA_PATH", "/media")
MOVIES_TRANSIENT = os.environ.get("TRANSIENT_PATH", os.path.join(BASE_MEDIA_PATH, "Movies"))
MOVIES_KEEP = os.environ.get("ARCHIVE_PATH", os.path.join(BASE_MEDIA_PATH, "Movies_keep"))
# The "Leaving Soon" folder: point a Jellyfin library at this so the family can still watch these.
MOVIES_REMOVAL_QUEUE = os.environ.get("REMOVAL_PATH", os.path.join(BASE_MEDIA_PATH, "Movies_removal"))

# The same folders as RADARR sees them (its container paths are usually different)
RADARR_KEEP_ROOT = os.environ.get("RADARR_KEEP_ROOT", MOVIES_KEEP)
RADARR_REMOVAL_ROOT = os.environ.get("RADARR_REMOVAL_ROOT", MOVIES_REMOVAL_QUEUE)

STATE_FILE = os.environ.get("STATE_FILE", "/app/logs/auditor_state.json")
ACTION_LOG_FILE = os.environ.get("ACTION_LOG_FILE", "/app/logs/auditor_actions.jsonl")

# Policy timers
MOVIE_WAIT_DAYS = 30        # Time in the normal Movies folder before entering Leaving Soon
TV_WAIT_DAYS = 60           # (TV comes later)
REMOVAL_QUEUE_DAYS = 7      # Time in Leaving Soon before permanent deletion

# Safety cap: max number of "queue for removal" + "delete" actions per run.
# Moves to Keep are not counted. Leftovers are picked up on the next run.
MAX_ACTIONS_PER_RUN = int(os.environ.get("MAX_ACTIONS_PER_RUN", "10"))
_actions_taken = 0


def log(msg: str):
    print(("[DRY RUN] " if DRY_RUN else "") + msg)


def record_action(action: str, folder: str, detail: str = ""):
    """Append one line (JSON) to the permanent action log. Dry-run entries are flagged dry_run=true."""
    entry = {
        "time": datetime.datetime.now().isoformat(timespec="seconds"),
        "dry_run": DRY_RUN,
        "action": action,
        "folder": folder,
        "detail": detail,
    }
    try:
        os.makedirs(os.path.dirname(ACTION_LOG_FILE), exist_ok=True)
        with open(ACTION_LOG_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        print(f"[LOG ERROR] Could not write action log {ACTION_LOG_FILE}: {e}")


def action_allowed(description: str) -> bool:
    global _actions_taken
    if _actions_taken >= MAX_ACTIONS_PER_RUN:
        print(f"[CAP REACHED] Skipping '{description}' (limit {MAX_ACTIONS_PER_RUN} queue/delete actions per run).")
        record_action("cap_skipped", description, f"limit {MAX_ACTIONS_PER_RUN} per run")
        return False
    _actions_taken += 1
    return True


# ==============================================
# --- STATE (remembers when we first saw / queued a folder) ---
# ==============================================

def load_state() -> Dict[str, Dict[str, str]]:
    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}
    state.setdefault("first_seen", {})
    state.setdefault("queued", {})
    return state


def save_state(state: Dict[str, Dict[str, str]]):
    # Saved even in dry run: it only holds our own bookkeeping, never touches your media.
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        tmp_path = STATE_FILE + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp_path, STATE_FILE)  # atomic: readers never see a half-written file
        print(f"\n[STATE] Saved {len(state['first_seen'])} tracked folders and "
              f"{len(state['queued'])} queued items to {os.path.abspath(STATE_FILE)}")
    except Exception as e:
        print(f"\n[STATE ERROR] Could not save {STATE_FILE}: {e}")


def days_since(iso_timestamp: str) -> int:
    return (datetime.datetime.now() - datetime.datetime.fromisoformat(iso_timestamp)).days


# ==============================================
# --- JELLYFIN: who favorited / tagged what ---
# ==============================================

def jellyfin_get(path: str, params: Optional[dict] = None):
    headers = {
        "Authorization": f'MediaBrowser Token="{JELLYFIN_TOKEN}"',  # current style
        "X-Emby-Token": JELLYFIN_TOKEN,                              # legacy style
    }
    r = requests.get(f"{JELLYFIN_URL}{path}", headers=headers, params=params, timeout=30)
    if r.status_code == 401:
        raise SystemExit(
            f"[ERROR] Jellyfin rejected the token (401). Token length seen: {len(JELLYFIN_TOKEN)} chars. "
            "Create an API key under Dashboard > API Keys and check it has no quotes/spaces in your compose file.")
    r.raise_for_status()
    return r.json()


def get_movie_signals() -> Dict[str, Dict[str, Any]]:
    """
    Returns {folder_name: {played, favorite, disliked}} combined across ALL Jellyfin users and ALL libraries
    (including your Leaving Soon library). Matching is by folder name, e.g. 'Pretty Woman (1990)'.
    """
    signals: Dict[str, Dict[str, Any]] = {}
    for user in jellyfin_get("/Users"):
        data = jellyfin_get(f"/Users/{user['Id']}/Items", {
            "Recursive": "true",
            "IncludeItemTypes": "Movie",
            "Fields": "Path,Tags",
        })
        for item in data.get("Items", []):
            folder = os.path.basename(os.path.dirname(item.get("Path", "")))
            if not folder:
                continue
            user_data = item.get("UserData", {})
            sig = signals.setdefault(folder, {"played": False, "favorite": False, "disliked": False})
            sig["played"] = sig["played"] or bool(user_data.get("Played")) or user_data.get("PlayCount", 0) > 0
            sig["favorite"] = sig["favorite"] or bool(user_data.get("IsFavorite"))
            if DISLIKE_TAG.lower() in [t.lower() for t in item.get("Tags", [])]:
                sig["disliked"] = True
    return signals


# ==============================================
# --- RADARR: notify about moves and removals ---
# ==============================================

_radarr_cache: Optional[list] = None


def radarr_headers():
    return {"X-Api-Key": RADARR_KEY}


def radarr_find_movie(folder_name: str) -> Optional[dict]:
    global _radarr_cache
    if _radarr_cache is None:
        r = requests.get(f"{RADARR_URL}/api/v3/movie", headers=radarr_headers(), timeout=60)
        r.raise_for_status()
        _radarr_cache = r.json()
    for movie in _radarr_cache:
        if os.path.basename(movie.get("path", "").rstrip("/")) == folder_name:
            return movie
    return None


def notify_radarr_moved(folder_name: str, radarr_root: str, monitored: Optional[bool] = None):
    """Tell Radarr the movie's new location. If monitored is True/False, also set its monitoring."""
    if not RADARR_URL:
        print("[WARN] RADARR_URL not set; skipping Radarr notification.")
        return
    movie = radarr_find_movie(folder_name)
    if not movie:
        print(f"[WARN] Radarr has no movie with folder '{folder_name}'; skipping notification.")
        return
    new_path = posixpath.join(radarr_root, folder_name)
    extra = "" if monitored is None else f", monitored={monitored}"
    log(f"Radarr: update '{folder_name}' path -> {new_path}{extra}")
    if DRY_RUN:
        return
    movie["path"] = new_path
    if monitored is not None:
        movie["monitored"] = monitored
    r = requests.put(f"{RADARR_URL}/api/v3/movie/{movie['id']}",
                     headers=radarr_headers(), params={"moveFiles": "false"},
                     json=movie, timeout=60)
    r.raise_for_status()


# ==============================================
# --- DISK ACTIONS ---
# ==============================================

def safe_move_directory(source_dir: str, destination_parent_dir: str) -> bool:
    package_name = os.path.basename(os.path.normpath(source_dir))
    destination_path = os.path.join(destination_parent_dir, package_name)

    log(f"MOVE '{os.path.abspath(source_dir)}' -> '{os.path.abspath(destination_path)}'")
    if DRY_RUN:
        return True
    try:
        os.makedirs(destination_parent_dir, exist_ok=True)
        if os.path.exists(destination_path):
            print(f"[SKIPPED] Destination already exists: {destination_path}")
            return False
        shutil.move(source_dir, destination_path)
        print(f"[SUCCESS] '{package_name}' moved to {destination_path}")
        return True
    except Exception as e:
        print(f"[FATAL ERROR] Failed to move {package_name}: {e}")
        return False


def remove_movie(folder_name: str, folder_path: str):
    """Delete via Radarr when possible (it removes the files and its own record); else delete the folder."""
    movie = radarr_find_movie(folder_name) if RADARR_URL else None
    if movie:
        log(f"Radarr: DELETE '{folder_name}' (with files)")
        if not DRY_RUN:
            r = requests.delete(f"{RADARR_URL}/api/v3/movie/{movie['id']}",
                                headers=radarr_headers(),
                                params={"deleteFiles": "true", "addImportExclusion": "false"},
                                timeout=120)
            r.raise_for_status()
    else:
        log(f"No Radarr entry; deleting folder directly: {folder_path}")
        if not DRY_RUN:
            shutil.rmtree(folder_path)


# ==============================================
# --- THE BRAIN: MOVIE LIFECYCLE ---
# ==============================================

def queue_for_removal(folder: str, path: str, state: dict, reason: str):
    """Move into Leaving Soon and tell Radarr to stop monitoring so it won't re-download."""
    if not action_allowed(f"queue {folder}"):
        return
    if safe_move_directory(path, MOVIES_REMOVAL_QUEUE):
        if not DRY_RUN:
            state["queued"][folder] = datetime.datetime.now().isoformat()
        notify_radarr_moved(folder, RADARR_REMOVAL_ROOT, monitored=False)
        record_action("queue", folder, reason)


def audit_removal_queue(signals: dict, state: dict):
    """Leaving Soon: favorited movies are rescued to Keep; the rest are deleted after REMOVAL_QUEUE_DAYS."""
    if not os.path.isdir(MOVIES_REMOVAL_QUEUE):
        return
    for folder in sorted(os.listdir(MOVIES_REMOVAL_QUEUE)):
        path = os.path.join(MOVIES_REMOVAL_QUEUE, folder)
        if not os.path.isdir(path):
            continue

        sig = signals.get(folder)
        if sig and sig["favorite"]:
            print(f"\n[{folder}] In Leaving Soon but favorited: rescue to Keep.")
            if safe_move_directory(path, MOVIES_KEEP):
                if not DRY_RUN:
                    state["queued"].pop(folder, None)
                notify_radarr_moved(folder, RADARR_KEEP_ROOT, monitored=True)
                record_action("rescue", folder, "favorited while in Leaving Soon")
            continue

        queued_at = state["queued"].get(folder)
        if queued_at is None:
            queued_at = datetime.datetime.now().isoformat()
            if not DRY_RUN:
                state["queued"][folder] = queued_at
        age = days_since(queued_at)

        if age >= REMOVAL_QUEUE_DAYS:
            print(f"\n[{folder}] In Leaving Soon {age}d: deleting.")
            if action_allowed(f"delete {folder}"):
                remove_movie(folder, path)
                record_action("delete", folder, f"in Leaving Soon {age} days")
                if not DRY_RUN:
                    state["queued"].pop(folder, None)
        else:
            print(f"\n[{folder}] In Leaving Soon {age}d ({REMOVAL_QUEUE_DAYS - age} days left).")


def audit_transient_movies(signals: dict, state: dict):
    if not os.path.isdir(MOVIES_TRANSIENT):
        print(f"[ERROR] Transient folder not found: {MOVIES_TRANSIENT}")
        return

    folders = sorted(f for f in os.listdir(MOVIES_TRANSIENT)
                     if os.path.isdir(os.path.join(MOVIES_TRANSIENT, f)))

    for folder in folders:
        path = os.path.join(MOVIES_TRANSIENT, folder)

        sig = signals.get(folder)
        if sig is None:
            print(f"\n[{folder}] Not found in Jellyfin yet (library scan pending?). Skipping.")
            continue

        # Grace period: the 30-day clock starts the first time the script sees a folder,
        # no matter how old the folder is on disk.
        first_seen = state["first_seen"].setdefault(folder, datetime.datetime.now().isoformat())
        age = days_since(first_seen)
        print(f"\n[{folder}] age={age}d played={sig['played']} favorite={sig['favorite']} disliked={sig['disliked']}")

        # Priority 1: favorited (watched or not) -> keep
        if sig["favorite"]:
            print("-> Favorited: move to Keep.")
            if safe_move_directory(path, MOVIES_KEEP):
                notify_radarr_moved(folder, RADARR_KEEP_ROOT)
                record_action("keep", folder, "favorited")
        # Priority 2: tagged not-at-all -> Leaving Soon right away
        elif sig["disliked"]:
            print("-> Tagged not-at-all: move to Leaving Soon.")
            queue_for_removal(folder, path, state, f"tagged {DISLIKE_TAG}")
        # Priority 3: still no decision after the waiting period -> Leaving Soon
        elif age >= MOVIE_WAIT_DAYS:
            print(f"-> No favorite after {MOVIE_WAIT_DAYS}+ days: move to Leaving Soon.")
            queue_for_removal(folder, path, state, f"no favorite after {age} days")
        else:
            print(f"-> Waiting ({MOVIE_WAIT_DAYS - age} days left to favorite it).")

    # Forget folders that have left the Movies folder
    for gone in set(state["first_seen"]) - set(folders):
        state["first_seen"].pop(gone, None)


# ==============================================
# --- MAIN ---
# ==============================================

# 0 = run once and exit (use with an external scheduler). Any positive number = stay running
# and repeat every N hours, so the container never exits and never restarts.
RUN_INTERVAL_HOURS = float(os.environ.get("RUN_INTERVAL_HOURS", "0"))


def run_once():
    global _actions_taken, _radarr_cache
    _actions_taken = 0      # the action cap applies per run
    _radarr_cache = None    # re-read Radarr's movie list every run

    print("\n=== Media Collection Auditor (MOVIES) ===")
    print(f"Run started {datetime.datetime.now().isoformat(timespec='seconds')}")
    print("DRY RUN: no changes will be made to your media." if DRY_RUN else "LIVE MODE: changes WILL be made.")

    if not JELLYFIN_TOKEN:
        raise SystemExit("[ERROR] JELLYFIN_API_TOKEN is not set.")

    state = load_state()
    movie_signals = get_movie_signals()
    audit_removal_queue(movie_signals, state)
    audit_transient_movies(movie_signals, state)
    save_state(state)
    record_action("run_complete", "-", f"{_actions_taken} queue/delete actions this run")


if __name__ == "__main__":
    if RUN_INTERVAL_HOURS <= 0:
        run_once()
    else:
        print(f"Loop mode: running every {RUN_INTERVAL_HOURS} hours.")
        while True:
            try:
                run_once()
            except (Exception, SystemExit) as e:
                # In loop mode an error (Jellyfin down, bad token, etc.) must not kill the
                # container, or Docker would restart it and hit the APIs again right away.
                print(f"[RUN FAILED] {e}")
                record_action("run_failed", "-", str(e)[:200])
            print(f"Sleeping {RUN_INTERVAL_HOURS} hours until the next run.")
            time.sleep(RUN_INTERVAL_HOURS * 3600)