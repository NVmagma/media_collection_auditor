import os
import json
import time
import shutil
import posixpath
import datetime
from typing import Dict, Any, Optional, List

import requests
from dotenv import load_dotenv

# ==============================================
# --- CONFIGURATION ---
# ==============================================
load_dotenv()


def env_flag(name: str, default: bool) -> bool:
    return os.environ.get(name, str(default)).strip().lower() == "true"


# Safety first: nothing is moved, deleted, or sent to Radarr/Sonarr unless DRY_RUN=false.
DRY_RUN = os.environ.get("DRY_RUN", "true").strip().lower() != "false"

# Jellyfin (decides favorited / tags)
JELLYFIN_URL = os.environ.get("JELLYFIN_HOST_URL", "http://localhost:8096").rstrip("/")
JELLYFIN_TOKEN = (os.environ.get("JELLYFIN_API_TOKEN") or "").strip().strip("'\"")
DISLIKE_TAG = os.environ.get("DISLIKE_TAG", "not-at-all")  # Jellyfin tag meaning "family hated it"

# Radarr (movies) and Sonarr (TV)
RADARR_URL = os.environ.get("RADARR_URL", "").rstrip("/")
RADARR_KEY = os.environ.get("RADARR_API_KEY")
SONARR_URL = os.environ.get("SONARR_URL", "").rstrip("/")
SONARR_KEY = os.environ.get("SONARR_API_KEY")

ENABLE_MOVIES = env_flag("ENABLE_MOVIES", True)
ENABLE_TV = env_flag("ENABLE_TV", False)

# Only used to build default folder paths when you don't set the individual *_PATH variables.
BASE_MEDIA_PATH = os.environ.get("MEDIA_PATH", "/media")

STATE_FILE = os.environ.get("STATE_FILE", "/app/logs/auditor_state.json")
ACTION_LOG_FILE = os.environ.get("ACTION_LOG_FILE", "/app/logs/auditor_actions.jsonl")

# Lifecycle timers (days)
MOVIE_WAIT_DAYS = int(os.environ.get("MOVIE_WAIT_DAYS", "30"))   # Movies: time in Transient before Holding
TV_WAIT_DAYS = int(os.environ.get("TV_WAIT_DAYS", "60"))         # Shows: same, but longer
HOLDING_DAYS = int(os.environ.get("HOLDING_DAYS", "7"))          # Time in Holding ("Leaving Soon") before Removal
REMOVAL_DAYS = int(os.environ.get("REMOVAL_DAYS", "7"))          # Time in Removal before permanent deletion

# TV only: a show that keeps getting new episodes restarts its waiting clock, so airing shows
# are not cleaned up while they're still being delivered. Set to false for a strict clock.
TV_NEW_EPISODES_RESET_CLOCK = env_flag("TV_NEW_EPISODES_RESET_CLOCK", True)

# Season pruning (TV only, off by default). For shows in the TV Keep folder, delete every season
# except the latest one -- unless the show has the keep-all tag in Jellyfin (e.g. Brooklyn Nine-Nine).
ENABLE_SEASON_PRUNING = env_flag("ENABLE_SEASON_PRUNING", False)
KEEP_ALL_SEASONS_TAG = os.environ.get("KEEP_ALL_SEASONS_TAG", "keep-all-seasons")
# Safety delay 1: a show must have been seen in Keep this long before anything is pruned,
# which gives you time to add the keep-all tag to your existing favorites.
SEASON_PRUNE_GRACE_DAYS = int(os.environ.get("SEASON_PRUNE_GRACE_DAYS", "30"))
# Safety delay 2: older seasons are only pruned once the newest season has been around this long,
# so a brand-new season premiere doesn't instantly wipe the season you wanted to rewatch.
SEASON_PRUNE_AFTER_NEW_SEASON_DAYS = int(os.environ.get("SEASON_PRUNE_AFTER_NEW_SEASON_DAYS", "7"))

# Safety cap: max number of "move into Holding" + "permanently delete" actions per run
# (movies and TV combined). Everything else is unlimited. Leftovers are picked up on the next run.
MAX_ACTIONS_PER_RUN = int(os.environ.get("MAX_ACTIONS_PER_RUN", "10"))
_actions_taken = 0

# 0 = run once and exit (use with an external scheduler). Any positive number = stay running
# and repeat every N hours, so the container never exits and never restarts.
RUN_INTERVAL_HOURS = float(os.environ.get("RUN_INTERVAL_HOURS", "0"))


def log(msg: str):
    print(("[DRY RUN] " if DRY_RUN else "") + msg)


def record_action(action: str, folder: str, detail: str = "", library: str = "Movies"):
    """Append one line (JSON) to the permanent action log. Dry-run entries are flagged dry_run=true."""
    entry = {
        "time": datetime.datetime.now().isoformat(timespec="seconds"),
        "dry_run": DRY_RUN,
        "library": library,
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


def action_allowed(description: str, library: str) -> bool:
    global _actions_taken
    if _actions_taken >= MAX_ACTIONS_PER_RUN:
        print(f"[CAP REACHED] Skipping '{description}' (limit {MAX_ACTIONS_PER_RUN} hold/delete actions per run).")
        record_action("cap_skipped", description, f"limit {MAX_ACTIONS_PER_RUN} per run", library)
        return False
    _actions_taken += 1
    return True


# ==============================================
# --- STATE (remembers when we first saw / moved a folder) ---
# ==============================================
# Movie keys are the bare folder name (kept that way so existing state files still work).
# TV keys are prefixed with "TV/" so names can never collide.
#   first_seen : when a folder was first seen in Transient (starts the waiting clock)
#   queued     : when a folder entered Holding
#   in_removal : when a folder entered Removal
#   keep_seen  : when a show was first seen in Keep (season pruning grace period)

def load_state() -> Dict[str, Dict[str, str]]:
    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        state = {}
    for section in ("first_seen", "queued", "in_removal", "keep_seen"):
        state.setdefault(section, {})
    return state


def save_state(state: Dict[str, Dict[str, str]]):
    # Saved even in dry run: it only holds our own bookkeeping, never touches your media.
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        tmp_path = STATE_FILE + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(state, f, indent=2)
        os.replace(tmp_path, STATE_FILE)  # atomic: readers never see a half-written file
        print(f"\n[STATE] Saved {len(state['first_seen'])} tracked folders, {len(state['queued'])} in holding, "
              f"{len(state['in_removal'])} in removal to {os.path.abspath(STATE_FILE)}")
    except Exception as e:
        print(f"\n[STATE ERROR] Could not save {STATE_FILE}: {e}")


def state_key(lib: dict, folder: str) -> str:
    return f"{lib['state_prefix']}{folder}"


def key_belongs_to(lib: dict, key: str) -> bool:
    if lib["state_prefix"]:
        return key.startswith(lib["state_prefix"])
    return "/" not in key  # movie keys are bare folder names


def days_between(start: datetime.datetime) -> int:
    return (datetime.datetime.now() - start).days


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


def get_signals(jellyfin_type: str) -> Dict[str, Dict[str, Any]]:
    """
    Returns {folder_name: {played, favorite, disliked, keep_all}} combined across ALL Jellyfin users and libraries.
    jellyfin_type is "Movie" or "Series". For a Series, favorite/tags must be set on the SHOW itself
    (not on a season or episode). Matching is by folder name, e.g. 'Pretty Woman (1990)'.
    """
    signals: Dict[str, Dict[str, Any]] = {}
    for user in jellyfin_get("/Users"):
        data = jellyfin_get(f"/Users/{user['Id']}/Items", {
            "Recursive": "true",
            "IncludeItemTypes": jellyfin_type,
            "Fields": "Path,Tags",
        })
        for item in data.get("Items", []):
            path = item.get("Path", "")
            if jellyfin_type == "Movie":
                folder = os.path.basename(os.path.dirname(path))   # path is the video file
            else:
                folder = os.path.basename(path.rstrip("/"))       # path is the show's folder
            if not folder:
                continue
            user_data = item.get("UserData", {})
            sig = signals.setdefault(folder, {"played": False, "favorite": False,
                                              "disliked": False, "keep_all": False})
            sig["played"] = sig["played"] or bool(user_data.get("Played")) or user_data.get("PlayCount", 0) > 0
            sig["favorite"] = sig["favorite"] or bool(user_data.get("IsFavorite"))
            tags = [t.lower() for t in item.get("Tags", [])]
            if DISLIKE_TAG.lower() in tags:
                sig["disliked"] = True
            if KEEP_ALL_SEASONS_TAG.lower() in tags:
                sig["keep_all"] = True
    return signals


# ==============================================
# --- RADARR / SONARR: notify about moves and removals ---
# ==============================================

class ArrClient:
    """Talks to Radarr (resource='movie') or Sonarr (resource='series') using the same v3 API shape."""

    def __init__(self, name: str, url: str, key: Optional[str], resource: str):
        self.name, self.url, self.key, self.resource = name, url, key, resource
        self._cache: Optional[List[dict]] = None

    @property
    def enabled(self) -> bool:
        return bool(self.url and self.key)

    def reset(self):
        self._cache = None

    def _headers(self):
        return {"X-Api-Key": self.key}

    def find(self, folder_name: str) -> Optional[dict]:
        if self._cache is None:
            r = requests.get(f"{self.url}/api/v3/{self.resource}", headers=self._headers(), timeout=60)
            r.raise_for_status()
            self._cache = r.json()
        for item in self._cache:
            if os.path.basename(item.get("path", "").rstrip("/")) == folder_name:
                return item
        return None

    def notify_moved(self, folder_name: str, root: str, monitored: Optional[bool] = None):
        """Tell it the new location. If monitored is True/False, also set its monitoring."""
        if not self.enabled:
            print(f"[WARN] {self.name} URL/API key not set; skipping {self.name} notification.")
            return
        item = self.find(folder_name)
        if not item:
            print(f"[WARN] {self.name} has no entry with folder '{folder_name}'; skipping notification.")
            return
        new_path = posixpath.join(root, folder_name)
        extra = "" if monitored is None else f", monitored={monitored}"
        log(f"{self.name}: update '{folder_name}' path -> {new_path}{extra}")
        if DRY_RUN:
            return
        item["path"] = new_path
        if monitored is not None:
            item["monitored"] = monitored
        r = requests.put(f"{self.url}/api/v3/{self.resource}/{item['id']}",
                         headers=self._headers(), params={"moveFiles": "false"},
                         json=item, timeout=60)
        r.raise_for_status()

    def delete(self, item: dict):
        """Delete the entry AND its files (so it also cleans its own records)."""
        r = requests.delete(f"{self.url}/api/v3/{self.resource}/{item['id']}",
                            headers=self._headers(),
                            params={"deleteFiles": "true", "addImportExclusion": "false"},
                            timeout=120)
        r.raise_for_status()

    # --- Sonarr only (season pruning) ---

    def episode_files(self, item: dict) -> List[dict]:
        """All downloaded episode files for a series (each has seasonNumber, id, dateAdded)."""
        r = requests.get(f"{self.url}/api/v3/episodefile", headers=self._headers(),
                         params={"seriesId": item["id"]}, timeout=60)
        r.raise_for_status()
        return r.json()

    def prune_seasons(self, item: dict, season_numbers: List[int], files: List[dict]):
        """Unmonitor the given seasons (so they're never re-downloaded), then delete their episode files."""
        log(f"{self.name}: unmonitor seasons {season_numbers} and delete {len(files)} episode files "
            f"of '{os.path.basename(item.get('path', '').rstrip('/'))}'")
        if DRY_RUN:
            return
        for season in item.get("seasons", []):
            if season.get("seasonNumber") in season_numbers:
                season["monitored"] = False
        r = requests.put(f"{self.url}/api/v3/{self.resource}/{item['id']}",
                         headers=self._headers(), params={"moveFiles": "false"},
                         json=item, timeout=60)
        r.raise_for_status()
        for f in files:
            d = requests.delete(f"{self.url}/api/v3/episodefile/{f['id']}",
                                headers=self._headers(), timeout=60)
            d.raise_for_status()


radarr = ArrClient("Radarr", RADARR_URL, RADARR_KEY, "movie")
sonarr = ArrClient("Sonarr", SONARR_URL, SONARR_KEY, "series")


# ==============================================
# --- LIBRARIES (one entry per kind of media, configured the same way) ---
# ==============================================
# For each prefix (RADARR / SONARR) the folders are set with the same four variables:
#   <PREFIX>_TRANSIENT_PATH   where new media lands and waits
#   <PREFIX>_HOLDING_PATH     "Leaving Soon": point a Jellyfin library here
#   <PREFIX>_KEEP_PATH        favorites live here for good
#   <PREFIX>_REMOVAL_PATH     final stop before permanent deletion
# Only if Radarr/Sonarr see these folders at DIFFERENT paths than this container does, also set:
#   <PREFIX>_APP_HOLDING_PATH / <PREFIX>_APP_KEEP_PATH / <PREFIX>_APP_REMOVAL_PATH

def library_paths(prefix: str, default_folders: Dict[str, str]) -> Dict[str, str]:
    paths = {}
    for kind in ("transient", "holding", "keep", "removal"):
        value = (os.environ.get(f"{prefix}_{kind.upper()}_PATH") or "").strip()
        paths[kind] = value or os.path.join(BASE_MEDIA_PATH, default_folders[kind])
    for kind in ("holding", "keep", "removal"):
        value = (os.environ.get(f"{prefix}_APP_{kind.upper()}_PATH") or "").strip()
        paths[f"app_{kind}"] = value or paths[kind]
    return paths


def build_libraries() -> List[dict]:
    libs = []
    if ENABLE_MOVIES:
        libs.append({
            "name": "Movies",
            "jellyfin_type": "Movie",
            "arr": radarr,
            **library_paths("RADARR", {"transient": "Movies", "holding": "Movies_hold",
                                       "keep": "Movies_keep", "removal": "Movies_removal"}),
            "wait_days": MOVIE_WAIT_DAYS,
            "new_content_resets_clock": False,
            "prune_seasons": False,
            "state_prefix": "",
        })
    if ENABLE_TV:
        libs.append({
            "name": "TV",
            "jellyfin_type": "Series",
            "arr": sonarr,
            **library_paths("SONARR", {"transient": "TV", "holding": "TV_hold",
                                       "keep": "TV_keep", "removal": "TV_removal"}),
            "wait_days": TV_WAIT_DAYS,
            "new_content_resets_clock": TV_NEW_EPISODES_RESET_CLOCK,
            "prune_seasons": ENABLE_SEASON_PRUNING,
            "state_prefix": "TV/",
        })
    return libs


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


def remove_media(arr: ArrClient, folder_name: str, folder_path: str):
    """Delete via Radarr/Sonarr when possible (it removes the files and its own record); else delete the folder."""
    item = arr.find(folder_name) if arr.enabled else None
    if item:
        log(f"{arr.name}: DELETE '{folder_name}' (with files)")
        if not DRY_RUN:
            arr.delete(item)
    else:
        log(f"No {arr.name} entry; deleting folder directly: {folder_path}")
        if not DRY_RUN:
            shutil.rmtree(folder_path)


def newest_mtime(path: str) -> Optional[datetime.datetime]:
    """Most recent modified time of anything inside a show's folder (new episodes bump this)."""
    newest = 0.0
    for root, dirs, files in os.walk(path):
        for name in files + dirs:
            try:
                newest = max(newest, os.path.getmtime(os.path.join(root, name)))
            except OSError:
                continue
    return datetime.datetime.fromtimestamp(newest) if newest else None


def list_folders(directory: str) -> List[str]:
    if not os.path.isdir(directory):
        return []
    return sorted(f for f in os.listdir(directory) if os.path.isdir(os.path.join(directory, f)))


# ==============================================
# --- THE BRAIN: LIFECYCLE (same rules for movies and TV) ---
#
#   Transient --(favorited)--------------------------> Keep
#   Transient --(not-at-all tag, or wait days)--> Holding --(favorited)--> Keep
#                                                    Holding --(HOLDING_DAYS)--> Removal --(REMOVAL_DAYS)--> deleted
# ==============================================

def move_to_holding(lib: dict, folder: str, path: str, state: dict, reason: str):
    """Move into Holding (Leaving Soon) and tell Radarr/Sonarr to stop monitoring so it isn't re-downloaded."""
    if not action_allowed(f"hold {folder}", lib["name"]):
        return
    if safe_move_directory(path, lib["holding"]):
        if not DRY_RUN:
            state["queued"][state_key(lib, folder)] = datetime.datetime.now().isoformat()
        lib["arr"].notify_moved(folder, lib["app_holding"], monitored=False)
        record_action("hold", folder, reason, lib["name"])


def audit_removal(lib: dict, state: dict):
    """Removal: after REMOVAL_DAYS the media is permanently deleted."""
    for folder in list_folders(lib["removal"]):
        path = os.path.join(lib["removal"], folder)
        key = state_key(lib, folder)

        entered = state["in_removal"].get(key)
        if entered is None:
            entered = datetime.datetime.now().isoformat()
            if not DRY_RUN:
                state["in_removal"][key] = entered
        age = days_between(datetime.datetime.fromisoformat(entered))

        if age >= REMOVAL_DAYS:
            print(f"\n[{lib['name']}: {folder}] In Removal {age}d: deleting permanently.")
            if action_allowed(f"delete {folder}", lib["name"]):
                remove_media(lib["arr"], folder, path)
                record_action("delete", folder, f"in Removal {age} days", lib["name"])
                if not DRY_RUN:
                    state["in_removal"].pop(key, None)
        else:
            print(f"\n[{lib['name']}: {folder}] In Removal {age}d ({REMOVAL_DAYS - age} days until deletion).")


def audit_holding(lib: dict, signals: dict, state: dict):
    """Holding (Leaving Soon): favorited items are rescued to Keep; the rest move to Removal after HOLDING_DAYS."""
    for folder in list_folders(lib["holding"]):
        path = os.path.join(lib["holding"], folder)
        key = state_key(lib, folder)

        sig = signals.get(folder)
        if sig and sig["favorite"]:
            print(f"\n[{lib['name']}: {folder}] In Holding but favorited: rescue to Keep.")
            if safe_move_directory(path, lib["keep"]):
                if not DRY_RUN:
                    state["queued"].pop(key, None)
                lib["arr"].notify_moved(folder, lib["app_keep"], monitored=True)
                record_action("rescue", folder, "favorited while in Holding", lib["name"])
            continue

        queued_at = state["queued"].get(key)
        if queued_at is None:
            queued_at = datetime.datetime.now().isoformat()
            if not DRY_RUN:
                state["queued"][key] = queued_at
        age = days_between(datetime.datetime.fromisoformat(queued_at))

        if age >= HOLDING_DAYS:
            print(f"\n[{lib['name']}: {folder}] In Holding {age}d, no favorite: move to Removal.")
            if safe_move_directory(path, lib["removal"]):
                if not DRY_RUN:
                    state["queued"].pop(key, None)
                    state["in_removal"][key] = datetime.datetime.now().isoformat()
                lib["arr"].notify_moved(folder, lib["app_removal"], monitored=False)
                record_action("to_removal", folder, f"in Holding {age} days", lib["name"])
        else:
            print(f"\n[{lib['name']}: {folder}] In Holding {age}d ({HOLDING_DAYS - age} days left to favorite it).")


def audit_transient(lib: dict, signals: dict, state: dict):
    transient = lib["transient"]
    if not os.path.isdir(transient):
        print(f"[ERROR] {lib['name']} folder not found: {transient}")
        return

    folders = list_folders(transient)

    for folder in folders:
        path = os.path.join(transient, folder)

        sig = signals.get(folder)
        if sig is None:
            print(f"\n[{lib['name']}: {folder}] Not found in Jellyfin yet (library scan pending?). Skipping.")
            continue

        # Grace period: the clock starts the first time the script sees a folder,
        # no matter how old the folder is on disk.
        key = state_key(lib, folder)
        first_seen = state["first_seen"].setdefault(key, datetime.datetime.now().isoformat())
        clock_start = datetime.datetime.fromisoformat(first_seen)
        note = ""
        if lib["new_content_resets_clock"]:
            newest = newest_mtime(path)
            if newest and newest > clock_start:
                clock_start = newest
                note = " (new episodes restarted the clock)"
        age = days_between(clock_start)
        wait = lib["wait_days"]
        print(f"\n[{lib['name']}: {folder}] age={age}d{note} played={sig['played']} "
              f"favorite={sig['favorite']} disliked={sig['disliked']}")

        # Priority 1: favorited (watched or not) -> keep
        if sig["favorite"]:
            print("-> Favorited: move to Keep.")
            if safe_move_directory(path, lib["keep"]):
                lib["arr"].notify_moved(folder, lib["app_keep"])
                record_action("keep", folder, "favorited", lib["name"])
        # Priority 2: tagged not-at-all -> Holding right away
        elif sig["disliked"]:
            print("-> Tagged not-at-all: move to Holding.")
            move_to_holding(lib, folder, path, state, f"tagged {DISLIKE_TAG}")
        # Priority 3: still no decision after the waiting period -> Holding
        elif age >= wait:
            print(f"-> No favorite after {wait}+ days: move to Holding.")
            move_to_holding(lib, folder, path, state, f"no favorite after {age} days")
        else:
            print(f"-> Waiting ({wait - age} days left to favorite it).")

    # Forget folders that have left this library's transient folder
    for key in list(state["first_seen"]):
        if key_belongs_to(lib, key) and key[len(lib["state_prefix"]):] not in folders:
            state["first_seen"].pop(key, None)


# ==============================================
# --- SEASON PRUNING (TV Keep folder) ---
# ==============================================

def parse_arr_date(value: Optional[str]) -> Optional[datetime.datetime]:
    """Sonarr dates look like 2026-10-01T12:34:56.789Z; keep just the first 19 characters."""
    if not value:
        return None
    try:
        return datetime.datetime.fromisoformat(value[:19])
    except ValueError:
        return None


def audit_keep_seasons(lib: dict, signals: dict, state: dict):
    """
    For favorited shows living in the Keep folder: delete every season except the latest one,
    unless the show carries the keep-all tag in Jellyfin. Specials (season 0) are never touched.
    Needs Sonarr, because Sonarr is what deletes the episode files and stops re-downloads.
    """
    keep_dir = lib["keep"]
    if not os.path.isdir(keep_dir):
        return
    arr = lib["arr"]
    if not arr.enabled:
        print("[WARN] Season pruning needs Sonarr (SONARR_URL / SONARR_API_KEY); skipping.")
        return

    folders = list_folders(keep_dir)
    print(f"\n--- Season pruning ({len(folders)} shows in Keep) ---")

    for folder in folders:
        label = f"[{lib['name']}: {folder}]"
        key = state_key(lib, folder)
        first_seen = state["keep_seen"].setdefault(key, datetime.datetime.now().isoformat())
        days_in_keep = days_between(datetime.datetime.fromisoformat(first_seen))

        sig = signals.get(folder)
        if sig is None:
            print(f"{label} Not found in Jellyfin; can't check its tags, so leaving it alone.")
            continue
        if sig.get("keep_all"):
            print(f"{label} Tagged '{KEEP_ALL_SEASONS_TAG}': keeping all seasons.")
            continue
        if days_in_keep < SEASON_PRUNE_GRACE_DAYS:
            print(f"{label} In Keep {days_in_keep}d: no pruning for another "
                  f"{SEASON_PRUNE_GRACE_DAYS - days_in_keep} days (time to add the keep-all tag).")
            continue

        item = arr.find(folder)
        if not item:
            print(f"{label} Not found in Sonarr; skipping.")
            continue

        by_season: Dict[int, List[dict]] = {}
        for f in arr.episode_files(item):
            season = f.get("seasonNumber", 0)
            if season >= 1:                      # ignore specials
                by_season.setdefault(season, []).append(f)
        if len(by_season) < 2:
            continue                             # nothing older than the latest season

        latest = max(by_season)
        added = [d for d in (parse_arr_date(f.get("dateAdded")) for f in by_season[latest]) if d]
        if not added:
            print(f"{label} Can't tell when season {latest} arrived; skipping.")
            continue
        latest_age = days_between(min(added))
        if latest_age < SEASON_PRUNE_AFTER_NEW_SEASON_DAYS:
            print(f"{label} Season {latest} arrived {latest_age}d ago: waiting "
                  f"{SEASON_PRUNE_AFTER_NEW_SEASON_DAYS - latest_age} more days before pruning older seasons.")
            continue

        old_seasons = sorted(s for s in by_season if s < latest)
        old_files = [f for s in old_seasons for f in by_season[s]]
        print(f"{label} Pruning seasons {old_seasons} ({len(old_files)} files); keeping season {latest}.")
        if not action_allowed(f"prune seasons {folder}", lib["name"]):
            continue
        arr.prune_seasons(item, old_seasons, old_files)
        record_action("prune_seasons", folder,
                      f"deleted seasons {old_seasons} ({len(old_files)} files); kept season {latest}",
                      lib["name"])

    # Forget shows that have left the Keep folder
    for key in list(state["keep_seen"]):
        if key_belongs_to(lib, key) and key[len(lib["state_prefix"]):] not in folders:
            state["keep_seen"].pop(key, None)


# ==============================================
# --- MAIN ---
# ==============================================

def run_once():
    global _actions_taken
    _actions_taken = 0      # the action cap applies per run
    radarr.reset()          # re-read Radarr's / Sonarr's lists every run
    sonarr.reset()

    print("\n=== Media Collection Auditor ===")
    print(f"Run started {datetime.datetime.now().isoformat(timespec='seconds')}")
    print("DRY RUN: no changes will be made to your media." if DRY_RUN else "LIVE MODE: changes WILL be made.")

    if not JELLYFIN_TOKEN:
        raise SystemExit("[ERROR] JELLYFIN_API_TOKEN is not set.")

    state = load_state()
    for lib in build_libraries():
        print(f"\n----- {lib['name']} -----")
        signals = get_signals(lib["jellyfin_type"])
        audit_removal(lib, state)               # delete what has served its time in Removal
        audit_holding(lib, signals, state)      # rescue favorites / move expired items to Removal
        audit_transient(lib, signals, state)    # keep favorites / move undecided items to Holding
        if lib.get("prune_seasons"):
            audit_keep_seasons(lib, signals, state)
    save_state(state)
    record_action("run_complete", "-", f"{_actions_taken} hold/delete actions this run", "All")


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
                record_action("run_failed", "-", str(e)[:200], "All")
            print(f"Sleeping {RUN_INTERVAL_HOURS} hours until the next run.")
            time.sleep(RUN_INTERVAL_HOURS * 3600)