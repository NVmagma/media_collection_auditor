# Compatibility helpers and the original audit loop. The Unraid image starts app.main.
import os
import sys
import json
import time
import shutil
import tempfile
import glob
import posixpath
import datetime
from typing import Dict, Any, Optional, List, Tuple

import requests
from lifecycle_decisions import decide

# ==============================================
# --- CONFIGURATION ---
# ==============================================

_TRUE = {"true", "1", "yes", "on"}
_FALSE = {"false", "0", "no", "off"}


def env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    if raw in _TRUE:
        return True
    if raw in _FALSE:
        return False
    raise SystemExit(f"[CONFIG ERROR] {name} must be true or false, got '{raw}'.")


def env_int(name: str, default: int, minimum: int = 0) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        raise SystemExit(f"[CONFIG ERROR] {name} must be a whole number, got '{raw}'.")
    if value < minimum:
        raise SystemExit(f"[CONFIG ERROR] {name} must be at least {minimum}, got {value}.")
    return value


def env_float(name: str, default: float, minimum: float = 0.0) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        raise SystemExit(f"[CONFIG ERROR] {name} must be a number, got '{raw}'.")
    if value < minimum:
        raise SystemExit(f"[CONFIG ERROR] {name} must be at least {minimum}, got {value}.")
    return value


# Safety first: nothing is moved, deleted, or sent to Radarr/Sonarr unless DRY_RUN=false.
DRY_RUN = env_flag("DRY_RUN", True)

# Jellyfin (decides favorited / tags)
JELLYFIN_URL = os.environ.get("JELLYFIN_HOST_URL", "http://localhost:8096").rstrip("/")
JELLYFIN_TOKEN = (os.environ.get("JELLYFIN_API_TOKEN") or "").strip().strip("'\"")
DISLIKE_TAG = os.environ.get("DISLIKE_TAG", "not-at-all")  # Jellyfin tag meaning "family hated it"
# Jellyfin tag meaning "never touch this": treated like a favorite (kept / rescued) and never season-pruned.
# Unlike a favorite, it is one global switch set by an admin, not per family member.
PROTECT_TAG = os.environ.get("PROTECT_TAG", "keep-forever")
KEEP_TAG = os.environ.get("KEEP_TAG", "keep")
FAVORITES_TRIGGER_KEEP = env_flag("FAVORITES_TRIGGER_KEEP", True)
JELLYFIN_REFRESH_AFTER_AUDIT = env_flag("JELLYFIN_REFRESH_AFTER_AUDIT", False)
_successful_media_moves = 0

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
MOVIE_WAIT_DAYS = env_int("MOVIE_WAIT_DAYS", 30)                 # Movies: time in Transient before Holding
TV_WAIT_DAYS = env_int("TV_WAIT_DAYS", 60)                       # Shows: same, but longer
HOLDING_DAYS = env_int("HOLDING_DAYS", 7, minimum=1)             # Time in Holding ("Leaving Soon") before Removal
REMOVAL_DAYS = env_int("REMOVAL_DAYS", 7, minimum=1)             # Time in Removal before permanent deletion

# TV only: a show that keeps getting new episodes restarts its waiting clock, so airing shows
# are not cleaned up while they're still being delivered. Set to false for a strict clock.
TV_NEW_EPISODES_RESET_CLOCK = env_flag("TV_NEW_EPISODES_RESET_CLOCK", True)

# Season pruning (TV only, off by default). For shows in the TV Keep folder, delete every season
# except the latest one -- unless the show has the keep-all tag in Jellyfin (e.g. Brooklyn Nine-Nine).
ENABLE_SEASON_PRUNING = env_flag("ENABLE_SEASON_PRUNING", False)
KEEP_ALL_SEASONS_TAG = os.environ.get("KEEP_ALL_SEASONS_TAG", "keep-all-seasons")
# Safety delay 1: a show must have been seen in Keep this long before anything is pruned,
# which gives you time to add the keep-all tag to your existing favorites.
SEASON_PRUNE_GRACE_DAYS = env_int("SEASON_PRUNE_GRACE_DAYS", 30)
# Safety delay 2: older seasons are only pruned once the newest season has been around this long,
# so a brand-new season premiere doesn't instantly wipe the season you wanted to rewatch.
SEASON_PRUNE_AFTER_NEW_SEASON_DAYS = env_int("SEASON_PRUNE_AFTER_NEW_SEASON_DAYS", 7)

# Safety cap: max number of SUCCESSFUL "move into Holding" + "permanently delete" + "season prune"
# actions per run (movies and TV combined). Everything else is unlimited. Leftovers wait for the next run.
MAX_ACTIONS_PER_RUN = env_int("MAX_ACTIONS_PER_RUN", 10)
_actions_taken = 0

# Deletion policy. Permanent deletion normally goes through Radarr/Sonarr, which know how to remove
# a title properly. If a title is NOT known to them (or they aren't configured), the script refuses
# to delete it itself unless you opt in here. Skipped titles are reported so you can handle them.
ALLOW_FILESYSTEM_DELETE = env_flag("ALLOW_FILESYSTEM_DELETE", False)
# Master gate: false blocks all permanent deletion, including Arr API deletion and season pruning.
ALLOW_PERMANENT_DELETE = env_flag("ALLOW_PERMANENT_DELETE", False)

# All of a library's folders should live on ONE mount, so moves are instant renames. If they don't,
# a move becomes a slow copy-then-delete that can be interrupted half way, so this is an error unless allowed.
ALLOW_CROSS_FILESYSTEM_MOVES = env_flag("ALLOW_CROSS_FILESYSTEM_MOVES", False)

# 0 = run once and exit (use with an external scheduler). Any positive number = stay running
# and repeat every N hours, so the container never exits and never restarts.
RUN_INTERVAL_HOURS = env_float("RUN_INTERVAL_HOURS", 0.0)

# Notifications (all optional; set any of the three). Webhook URLs are secrets: keep them in private application settings.
NOTIFY_DISCORD_WEBHOOK_URL = os.environ.get("NOTIFY_DISCORD_WEBHOOK_URL", "").strip()
NOTIFY_NTFY_URL = os.environ.get("NOTIFY_NTFY_URL", "").strip()          # e.g. https://ntfy.sh/your-topic
NOTIFY_NTFY_TOKEN = os.environ.get("NOTIFY_NTFY_TOKEN", "").strip()      # only for protected ntfy topics
NOTIFY_WEBHOOK_URL = os.environ.get("NOTIFY_WEBHOOK_URL", "").strip()    # generic: receives a JSON POST
NOTIFY_ON_DRY_RUN = env_flag("NOTIFY_ON_DRY_RUN", False)                 # send messages during dry runs too
NOTIFY_LEAVING_SOON_DIGEST = env_flag("NOTIFY_LEAVING_SOON_DIGEST", True)  # list what is still in Holding
NOTIFY_MAX_CHARS = 1800                                                  # Discord's limit is 2000

# Collected during each run and used for the run summary and the notification.
_events: List[dict] = []
_holding_status: List[dict] = []
_stats: Dict[str, int] = {"waiting": 0, "in_removal": 0}


def log(msg: str):
    print(("[DRY RUN] " if DRY_RUN else "") + msg)


def human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def record_action(action: str, folder: str, detail: str = "", library: str = "Movies",
                  status: str = "done", size_bytes: Optional[int] = None):
    """
    Append one line (JSON) to the permanent action log.
    status: "done" (it happened), "planned" (dry run: it WOULD happen), "failed" (it was attempted and
    did not work), or "skipped" (deliberately not done, e.g. blocked by a safety rule).
    """
    entry = {
        "time": datetime.datetime.now().isoformat(timespec="seconds"),
        "dry_run": DRY_RUN,
        "library": library,
        "action": action,
        "status": "planned" if (DRY_RUN and status == "done") else status,
        "folder": folder,
        "detail": detail,
    }
    if size_bytes is not None:
        entry["size_bytes"] = size_bytes
    _events.append(entry)
    try:
        os.makedirs(os.path.dirname(ACTION_LOG_FILE), exist_ok=True)
        with open(ACTION_LOG_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        print(f"[LOG ERROR] Could not write action log {ACTION_LOG_FILE}: {e}")


def action_allowed(description: str, library: str) -> bool:
    """True while the per-run cap has room. Call action_done() once the action has actually succeeded."""
    if _actions_taken >= MAX_ACTIONS_PER_RUN:
        print(f"[CAP REACHED] Skipping '{description}' (limit {MAX_ACTIONS_PER_RUN} hold/delete/prune actions per run).")
        record_action("cap_skipped", description, f"limit {MAX_ACTIONS_PER_RUN} per run", library, status="skipped")
        return False
    return True


def action_done():
    global _actions_taken
    _actions_taken += 1


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
    """Load tracking history; refuse to audit when an existing file is damaged."""
    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
    except FileNotFoundError:
        # A missing live file alongside an interrupted write is not a clean install.
        directory = os.path.dirname(os.path.abspath(STATE_FILE))
        abandoned = glob.glob(os.path.join(directory, ".auditor_state_*.tmp"))
        if abandoned:
            raise RuntimeError(
                f"Missing auditor state at {STATE_FILE} with interrupted writes present; "
                "refusing to reset tracking history"
            )
        state = {}  # A fresh installation has no tracking file yet.
    except (json.JSONDecodeError, UnicodeError, OSError) as exc:
        raise RuntimeError(
            f"Cannot read auditor state at {STATE_FILE}; refusing to reset tracking history"
        ) from exc
    sections = ("first_seen", "queued", "in_removal", "keep_seen", "arr_sync_pending")
    if not isinstance(state, dict) or any(
        section in state and not isinstance(state[section], dict)
        for section in sections
    ):
        raise RuntimeError(
            f"Invalid auditor state at {STATE_FILE}; refusing to reset tracking history"
        )
    for section in sections:
        state.setdefault(section, {})
    for section in ("first_seen", "queued", "in_removal", "keep_seen"):
        for key, timestamp in state[section].items():
            if not isinstance(key, str) or not key or not isinstance(timestamp, str):
                raise RuntimeError(f"Invalid {section} entry in {STATE_FILE}; refusing to audit")
            try:
                parsed = datetime.datetime.fromisoformat(timestamp)
            except ValueError as exc:
                raise RuntimeError(f"Invalid {section} timestamp in {STATE_FILE}; refusing to audit") from exc
            if parsed.tzinfo is not None:
                raise RuntimeError(f"Timezone-aware {section} timestamp in {STATE_FILE}; refusing to audit")
            if parsed > datetime.datetime.now():
                raise RuntimeError(f"Future {section} timestamp in {STATE_FILE}; refusing to audit")
    for key, entry in state["arr_sync_pending"].items():
        if (not isinstance(key, str) or not key or not isinstance(entry, dict)
                or entry.get("stage") not in ("holding", "keep", "removal")
                or not isinstance(entry.get("root"), str)
                or not entry["root"]
                or (entry.get("monitored") is not None
                    and type(entry["monitored"]) is not bool)):
            raise RuntimeError(f"Invalid Arr retry entry in {STATE_FILE}; refusing to audit")
    return state


def save_state(state: Dict[str, Dict[str, str]]):
    """Save JSON state only while holding the shared migration lock."""
    from state_lock import state_writer_lock

    # Fresh installations may not have a state directory yet. Create it
    # before opening the adjacent lock file, without touching existing state.
    os.makedirs(os.path.dirname(os.path.abspath(STATE_FILE)), exist_ok=True)
    with state_writer_lock(STATE_FILE):
        _save_state_unlocked(state)


def _save_state_unlocked(state: Dict[str, Dict[str, str]]):
    # Saved even in dry run: it only holds our own bookkeeping, never touches your media.
    tmp_path = None
    try:
        directory = os.path.dirname(os.path.abspath(STATE_FILE))
        os.makedirs(directory, exist_ok=True)
        # A unique temporary file avoids collisions between interrupted saves.
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8",
                                         dir=directory, prefix=".auditor_state_",
                                         suffix=".tmp", delete=False) as f:
            tmp_path = f.name
            json.dump(state, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, STATE_FILE)  # atomic: readers never see a half-written file
        tmp_path = None
        # Persist the directory entry as well as the file contents after a rename.
        # Not all platforms support directory fsync; do not silently ignore I/O errors.
        if os.name == "posix":
            dir_fd = os.open(directory, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        print(f"\n[STATE] Saved {len(state['first_seen'])} tracked folders, {len(state['queued'])} in holding, "
              f"{len(state['in_removal'])} in removal to {os.path.abspath(STATE_FILE)}")
    except Exception as e:
        print(f"\n[STATE ERROR] Could not save {STATE_FILE}: {e}")
        raise RuntimeError(f"Failed to persist auditor state to {STATE_FILE}") from e
    finally:
        if tmp_path is not None:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass  # Preserve the original write error; never touch the live state.


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
    Returns {folder_name: {played, favorite, disliked, keep_all, protected}} combined across ALL Jellyfin users
    and libraries. jellyfin_type is "Movie" or "Series". For a Series, favorite/tags must be set on the SHOW
    itself (not on a season or episode). Matching is by folder name, e.g. 'Pretty Woman (1990)'.
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
            sig = signals.setdefault(folder, {"played": False, "favorite": False, "disliked": False,
                                              "keep_all": False, "protected": False, "keep": False})
            sig["played"] = sig["played"] or bool(user_data.get("Played")) or user_data.get("PlayCount", 0) > 0
            sig["favorite"] = sig["favorite"] or bool(user_data.get("IsFavorite"))
            tags = [t.lower() for t in item.get("Tags", [])]
            if KEEP_TAG.lower() in tags:
                sig["keep"] = True
            if DISLIKE_TAG.lower() in tags:
                sig["disliked"] = True
            if KEEP_ALL_SEASONS_TAG.lower() in tags:
                sig["keep_all"] = True
            if PROTECT_TAG.lower() in tags:
                # Protected = treated as a favorite (kept / rescued) and never season-pruned.
                sig["protected"] = sig["keep_all"] = True
    return signals


# ==============================================
# --- RADARR / SONARR: notify about moves and removals ---
# ==============================================

class AmbiguousMatchError(Exception):
    """More than one Radarr/Sonarr entry uses the same folder name, so we can't tell which one is meant."""


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

    def check(self):
        """Raises if the service is unreachable or rejects the API key."""
        r = requests.get(f"{self.url}/api/v3/system/status", headers=self._headers(), timeout=15)
        r.raise_for_status()

    def find(self, folder_name: str) -> Optional[dict]:
        """The entry whose folder is named folder_name. Raises AmbiguousMatchError if several match."""
        if self._cache is None:
            r = requests.get(f"{self.url}/api/v3/{self.resource}", headers=self._headers(), timeout=60)
            r.raise_for_status()
            self._cache = r.json()
        matches = [item for item in self._cache
                   if os.path.basename(item.get("path", "").rstrip("/")) == folder_name]
        if len(matches) > 1:
            raise AmbiguousMatchError(f"{len(matches)} {self.name} entries use the folder name '{folder_name}'")
        return matches[0] if matches else None

    def notify_moved(self, folder_name: str, root: str, monitored: Optional[bool] = None) -> bool:
        """
        Tell it the new location (and optionally set monitoring).
        Returns False only if the update was attempted and FAILED; the caller records that.
        """
        if not self.enabled:
            print(f"[WARN] {self.name} URL/API key not set; skipping {self.name} notification.")
            return True
        try:
            item = self.find(folder_name)
            if not item:
                print(f"[WARN] {self.name} has no entry with folder '{folder_name}'; skipping notification.")
                return True
            new_path = posixpath.join(root, folder_name)
            extra = "" if monitored is None else f", monitored={monitored}"
            log(f"{self.name}: update '{folder_name}' path -> {new_path}{extra}")
            if DRY_RUN:
                return True
            payload = dict(item)
            payload["path"] = new_path
            if monitored is not None:
                payload["monitored"] = monitored
            r = requests.put(f"{self.url}/api/v3/{self.resource}/{item['id']}",
                             headers=self._headers(), params={"moveFiles": "false"},
                             json=payload, timeout=60)
            r.raise_for_status()
            item.update(payload)
            return True
        except (requests.RequestException, AmbiguousMatchError) as e:
            self._cache = None
            print(f"[WARN] {self.name} update failed for '{folder_name}' ({type(e).__name__}).")
            return False

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
        payload = dict(item)
        payload["seasons"] = [dict(s, monitored=False) if s.get("seasonNumber") in season_numbers else s
                              for s in item.get("seasons", [])]
        r = requests.put(f"{self.url}/api/v3/{self.resource}/{item['id']}",
                         headers=self._headers(), params={"moveFiles": "false"},
                         json=payload, timeout=60)
        r.raise_for_status()
        item.update(payload)
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

FOLDER_KINDS = ("transient", "holding", "keep", "removal")


def library_paths(prefix: str, default_folders: Dict[str, str]) -> Dict[str, str]:
    paths = {}
    for kind in FOLDER_KINDS:
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
# --- PREFLIGHT: refuse to run if the setup looks unsafe ---
# ==============================================

def filesystem_id(path: str) -> int:
    return os.stat(path).st_dev


def is_within(path: str, root: str) -> bool:
    """True if path is strictly inside root (symlinks resolved)."""
    real_path, real_root = os.path.realpath(path), os.path.realpath(root)
    try:
        return os.path.commonpath([real_path, real_root]) == real_root and real_path != real_root
    except ValueError:
        return False


def check_paths(libs: List[dict]) -> Tuple[List[str], List[str]]:
    """Folder checks. Nothing here touches the network. Returns (errors, warnings)."""
    errors: List[str] = []
    warnings: List[str] = []
    all_paths: List[Tuple[str, str, str]] = []   # (library, kind, real path)

    for lib in libs:
        name = lib["name"]
        folders = {kind: lib[kind] for kind in FOLDER_KINDS}

        for kind, path in folders.items():
            if not os.path.isdir(path):
                errors.append(f"{name}: the {kind} folder does not exist: {path} "
                              "(create it and check your volume mapping; the script never creates it for you)")
            elif not os.access(path, os.R_OK | os.W_OK | os.X_OK):
                errors.append(f"{name}: the {kind} folder is not writable: {path}")
            all_paths.append((name, kind, os.path.realpath(path)))

        kinds = list(folders)
        for i, first in enumerate(kinds):
            for second in kinds[i + 1:]:
                if (os.path.realpath(folders[first]) == os.path.realpath(folders[second])
                        or is_within(folders[first], folders[second])
                        or is_within(folders[second], folders[first])):
                    errors.append(f"{name}: the {first} and {second} folders are the same or overlap "
                                  f"({folders[first]} / {folders[second]})")

        existing = [p for p in folders.values() if os.path.isdir(p)]
        if len({filesystem_id(p) for p in existing}) > 1:
            message = (f"{name}: the folders are on different filesystems/mounts, so moves would be slow "
                       "copy-then-delete operations that can be interrupted half way. Map one parent folder "
                       "into the container instead of several separate ones.")
            if ALLOW_CROSS_FILESYSTEM_MOVES:
                warnings.append(message)
            else:
                errors.append(message + " (Set ALLOW_CROSS_FILESYSTEM_MOVES=true to accept this.)")

    # No two libraries may share a folder
    seen: Dict[str, str] = {}
    for library, kind, real in all_paths:
        label = f"{library} {kind}"
        if real in seen and seen[real].split(" ")[0] != library:
            errors.append(f"{label} folder is the same as the {seen[real]} folder: {real}")
        seen.setdefault(real, label)

    return errors, warnings


def check_services(libs: List[dict]) -> Tuple[List[str], List[str]]:
    """Network checks: Jellyfin and each enabled library's Radarr/Sonarr. Returns (errors, warnings)."""
    errors: List[str] = []
    warnings: List[str] = []
    try:
        jellyfin_get("/Users")
    except SystemExit as e:
        errors.append(str(e).replace("[ERROR] ", ""))
    except Exception as e:
        errors.append(f"Cannot reach Jellyfin ({type(e).__name__}). Check JELLYFIN_HOST_URL.")

    for lib in libs:
        arr = lib["arr"]
        if not arr.enabled:
            warnings.append(f"{lib['name']}: {arr.name} is not configured, so it will not be told about moves "
                            f"(it may re-download titles) and deletions need ALLOW_FILESYSTEM_DELETE=true.")
            continue
        try:
            arr.check()
        except Exception as e:
            errors.append(f"Cannot reach {arr.name} ({type(e).__name__}). "
                          f"Check {arr.name.upper()}_URL and {arr.name.upper()}_API_KEY.")
    return errors, warnings


def preflight(libs: List[dict]) -> Tuple[List[str], List[str]]:
    """Everything that must be true before the script is allowed to touch anything."""
    if not libs:
        return ["No libraries are enabled (set ENABLE_MOVIES and/or ENABLE_TV)."], []
    errors, warnings = check_paths(libs)
    if not errors:                       # don't bother the APIs if the folders are already wrong
        service_errors, service_warnings = check_services(libs)
        errors += service_errors
        warnings += service_warnings
    return errors, warnings


# ==============================================
# --- DISK ACTIONS ---
# ==============================================

def safe_move_directory(source_dir: str, destination_parent_dir: str) -> Optional[str]:
    """
    Move a folder into destination_parent_dir. Returns None on success, or a short error message.
    The destination folder must already exist (it is never created, so a missing mount can't
    silently turn into a local folder), and the move is verified afterwards.
    """
    package_name = os.path.basename(os.path.normpath(source_dir))
    destination_path = os.path.join(destination_parent_dir, package_name)

    log(f"MOVE '{os.path.abspath(source_dir)}' -> '{os.path.abspath(destination_path)}'")
    if DRY_RUN:
        return None
    try:
        if not os.path.isdir(destination_parent_dir):
            return f"destination folder is missing: {destination_parent_dir}"
        if os.path.exists(destination_path):
            return f"destination already exists: {destination_path}"
        shutil.move(source_dir, destination_path)
    except Exception as e:
        return f"{type(e).__name__}: {e}"
    if os.path.exists(source_dir) or not os.path.isdir(destination_path):
        return "move did not complete (source still present or destination missing)"
    global _successful_media_moves
    _successful_media_moves += 1
    print(f"[SUCCESS] '{package_name}' moved to {destination_path}")
    return None


def move_or_report(lib: dict, folder: str, source: str, destination_parent: str) -> bool:
    """Move a folder; on failure, say so loudly and record it. Nothing else should happen if this is False."""
    error = safe_move_directory(source, destination_parent)
    if error:
        print(f"[MOVE FAILED] {folder}: {error}")
        record_action("move_failed", folder, error, lib["name"], status="failed")
        return False
    return True


def sync_arr(lib: dict, folder: str, root: str, monitored: Optional[bool] = None,
             state: Optional[dict] = None, stage: Optional[str] = None):
    """Sync Arr; retain a retry request after a failed verified move."""
    arr = lib["arr"]
    key = state_key(lib, folder) if state is not None else None
    try:
        succeeded = arr.notify_moved(folder, root, monitored)
    except requests.RequestException:
        succeeded = False
    if succeeded:
        if state is not None and not DRY_RUN:
            state.setdefault("arr_sync_pending", {}).pop(key, None)
        return
    if state is not None and stage is not None and not DRY_RUN:
        state.setdefault("arr_sync_pending", {})[key] = {
            "stage": stage, "root": root, "monitored": monitored,
        }
    record_action("arr_sync_failed", folder,
                  f"{arr.name} was NOT updated after the move; retry pending if tracked",
                  lib["name"], status="failed")


def retry_pending_arr_sync(lib: dict, state: dict):
    """Retry only when the title exists in exactly its recorded destination."""
    pending = state.setdefault("arr_sync_pending", {})
    for key, entry in list(pending.items()):
        if not key_belongs_to(lib, key):
            continue
        folder = key[len(lib["state_prefix"]):]
        stage = entry.get("stage") if isinstance(entry, dict) else None
        if stage not in ("holding", "keep", "removal"):
            continue
        present = [kind for kind in FOLDER_KINDS
                   if os.path.isdir(os.path.join(lib[kind], folder))]
        if present != [stage]:
            record_action("arr_sync_retry_skipped", folder,
                          "Media location is missing or ambiguous; no Arr update attempted",
                          lib["name"], status="skipped")
            continue
        if DRY_RUN:
            continue
        # Use current configured Arr path, not an obsolete persisted root.
        sync_arr(lib, folder, lib["app_" + stage], entry.get("monitored"),
                 state=state, stage=stage)


def remove_media(lib: dict, folder_name: str, folder_path: str) -> bool:
    """
    Permanently delete a title from the Removal folder. Returns True only if it was (or, in a dry run,
    would be) deleted. Every refusal is recorded. The rules, in order:
      1. Never delete anything that isn't strictly inside this library's Removal folder.
      2. If Radarr/Sonarr are configured, they must know the title (exactly one entry), and the
         folder must really be gone afterwards.
      3. If they don't know it, or aren't configured, delete it ourselves ONLY with ALLOW_FILESYSTEM_DELETE=true.
    """
    arr = lib["arr"]
    name = lib["name"]

    if not ALLOW_PERMANENT_DELETE:
        message = "master permanent deletion switch is disabled"
        print(f"[DELETE SKIPPED] {folder_name}: {message}")
        record_action("delete_skipped", folder_name, message, name, status="skipped")
        return False

    if os.path.islink(folder_path) or not is_within(folder_path, lib["removal"]):
        message = "refusing to delete: path is not strictly inside the Removal folder"
        print(f"[DELETE REFUSED] {folder_name}: {message}")
        record_action("delete_skipped", folder_name, message, name, status="skipped")
        return False

    if arr.enabled:
        try:
            item = arr.find(folder_name)
        except AmbiguousMatchError as e:
            print(f"[DELETE REFUSED] {folder_name}: {e}")
            record_action("delete_skipped", folder_name, str(e), name, status="skipped")
            return False
        except requests.RequestException as e:
            print(f"[DELETE FAILED] {folder_name}: could not ask {arr.name} ({type(e).__name__})")
            record_action("delete_failed", folder_name, f"could not ask {arr.name} ({type(e).__name__})",
                          name, status="failed")
            return False

        if item:
            log(f"{arr.name}: DELETE '{folder_name}' (with files)")
            if DRY_RUN:
                return True
            try:
                arr.delete(item)
            except requests.RequestException as e:
                print(f"[DELETE FAILED] {folder_name}: {arr.name} refused ({type(e).__name__})")
                record_action("delete_failed", folder_name, f"{arr.name} refused the delete ({type(e).__name__})",
                              name, status="failed")
                return False
            if os.path.exists(folder_path):
                message = (f"{arr.name} reported success but the folder is still there; "
                           f"check that its path settings (e.g. {arr.name.upper()}_APP_REMOVAL_PATH) are right")
                print(f"[DELETE INCOMPLETE] {folder_name}: {message}")
                record_action("delete_failed", folder_name, message, name, status="failed")
                return False
            return True

    if not ALLOW_FILESYSTEM_DELETE:
        reason = f"not found in {arr.name}" if arr.enabled else f"{arr.name} is not configured"
        message = f"{reason}; delete it by hand, or set ALLOW_FILESYSTEM_DELETE=true to let the script do it"
        print(f"[DELETE SKIPPED] {folder_name}: {message}")
        record_action("delete_skipped", folder_name, message, name, status="skipped")
        return False

    log(f"No {arr.name} entry; deleting folder directly: {folder_path}")
    if DRY_RUN:
        return True
    try:
        shutil.rmtree(folder_path)
    except OSError as e:
        print(f"[DELETE FAILED] {folder_name}: {e}")
        record_action("delete_failed", folder_name, f"{type(e).__name__}: {e}", name, status="failed")
        return False
    return True


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


def folder_size(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                continue
    return total


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
    if move_or_report(lib, folder, path, lib["holding"]):
        action_done()
        if not DRY_RUN:
            key = state_key(lib, folder)
            state["queued"][key] = datetime.datetime.now().isoformat()
            state["first_seen"].pop(key, None)
        record_action("hold", folder, reason, lib["name"])
        sync_arr(lib, folder, lib["app_holding"], monitored=False, state=state, stage="holding")


def reconcile_moved_titles(lib: dict, state: dict):
    """Repair stale tracking after a move; never move or delete media here.

    Only reconcile a title when it exists in exactly one configured stage.
    Ambiguous or missing paths are left untouched for manual inspection.
    """
    stages = {
        "first_seen": "transient",
        "queued": "holding",
        "in_removal": "removal",
    }
    for section, source_stage in stages.items():
        for key in list(state[section]):
            if not key_belongs_to(lib, key):
                continue
            folder = key[len(lib["state_prefix"]):]
            present = [stage for stage in ("transient", "holding", "removal", "keep")
                       if os.path.isdir(os.path.join(lib[stage], folder))]
            if len(present) != 1 or present[0] == source_stage:
                continue
            # Never infer an age for a destination stage. Its audit will start
            # a fresh grace period if no timestamp was persisted.
            if not DRY_RUN:
                state[section].pop(key, None)
                # Conflicting history means the destination clock is not
                # trustworthy. Restart its grace period rather than inherit
                # an old timestamp that could authorize premature deletion.
                destination_section = {
                    "holding": "queued", "removal": "in_removal",
                }.get(present[0])
                if destination_section and key in state[destination_section]:
                    state[destination_section][key] = datetime.datetime.now().isoformat()
                if present[0] == "keep":
                    state["keep_seen"].setdefault(key, datetime.datetime.now().isoformat())
                # An interrupted move may have occurred before Arr was notified.
                # Queue only known forward transitions; never infer a backwards move.
                destination = present[0]
                if (source_stage, destination) in (
                    ("transient", "holding"), ("transient", "keep"),
                    ("holding", "removal"), ("holding", "keep"),
                    ("removal", "keep"),
                ):
                    state.setdefault("arr_sync_pending", {}).setdefault(key, {
                        "stage": destination,
                        "root": lib["app_" + destination],
                        "monitored": destination == "keep",
                    })
            print(f"[STATE RECONCILE] {lib['name']}: {folder} is in {present[0]}, "
                  f"not {source_stage}; stale {section} entry "
                  f"{'would be cleared' if DRY_RUN else 'cleared'}.")


def reconcile_untracked_keep(lib: dict, state: dict):
    """Record first observation of untracked Keep media, without moving files.

    Keep has no expiry clock. Never overwrite existing history or infer an
    earlier move date; skip folders that also appear in another stage.
    """
    for folder in list_folders(lib["keep"]):
        key = state_key(lib, folder)
        if any(key in state[section] for section in
               ("first_seen", "queued", "in_removal", "keep_seen")):
            continue
        if any(os.path.isdir(os.path.join(lib[stage], folder)) for stage in
               ("transient", "holding", "removal")):
            print(f"[STATE RECONCILE] {lib['name']}: {folder} is ambiguous; Keep tracking unchanged.")
            continue
        if not DRY_RUN:
            state["keep_seen"][key] = datetime.datetime.now().isoformat()
        print(f"[STATE RECONCILE] {lib['name']}: {folder} untracked in Keep; "
              f"{'would record' if DRY_RUN else 'recorded'} first observation (not original move date).")


def audit_removal(lib: dict, state: dict, signals: dict):
    """Removal: after REMOVAL_DAYS the media is permanently deleted."""
    for folder in list_folders(lib["removal"]):
        path = os.path.join(lib["removal"], folder)
        key = state_key(lib, folder)

        # An interrupted or copied move may leave the same title in two stages.
        # Do not use an old Removal clock to authorize deletion in that case.
        duplicates = [stage for stage in ("transient", "holding", "keep")
                      if os.path.isdir(os.path.join(lib[stage], folder))]
        if duplicates:
            print(f"\\n[{lib['name']}: {folder}] Removal paused: title also exists in "
                  f"{', '.join(duplicates)}; manual reconciliation required.")
            record_action("delete_skipped", folder,
                          f"Removal blocked: duplicate lifecycle folder in {', '.join(duplicates)}",
                          lib["name"], status="skipped")
            _stats["in_removal"] += 1
            continue

        entered = state["in_removal"].get(key)
        if entered is None:
            entered = datetime.datetime.now().isoformat()
            if not DRY_RUN:
                state["in_removal"][key] = entered
        age = days_between(datetime.datetime.fromisoformat(entered))

        sig = signals.get(folder)
        if sig is None:
            print(f"\n[{lib['name']}: {folder}] Removal paused: Jellyfin signals unavailable for this title.")
            _stats["in_removal"] += 1
            continue
        if sig.get("protected") or sig.get("keep") or (FAVORITES_TRIGGER_KEEP and sig.get("favorite")):
            print(f"\n[{lib['name']}: {folder}] Removal blocked: protected by Jellyfin keep tag or legacy favorite. Manual rescue required.")
            _stats["in_removal"] += 1
            continue
        if decide("Removal", age, REMOVAL_DAYS)[0] == "delete_candidate":
            print(f"\n[{lib['name']}: {folder}] In Removal {age}d: deleting permanently.")
            if action_allowed(f"delete {folder}", lib["name"]):
                size = folder_size(path)
                if remove_media(lib, folder, path):
                    action_done()
                    record_action("delete", folder, f"in Removal {age} days ({human_size(size)})",
                                  lib["name"], size_bytes=size)
                    if not DRY_RUN:
                        state["in_removal"].pop(key, None)
        else:
            _stats["in_removal"] += 1
            print(f"\n[{lib['name']}: {folder}] In Removal {age}d ({REMOVAL_DAYS - age} days until deletion).")


def audit_holding(lib: dict, signals: dict, state: dict):
    """Holding (Leaving Soon): favorited items are rescued to Keep; the rest move to Removal after HOLDING_DAYS."""
    for folder in list_folders(lib["holding"]):
        path = os.path.join(lib["holding"], folder)
        key = state_key(lib, folder)

        sig = signals.get(folder)
        if decide("Holding", None, HOLDING_DAYS, sig, FAVORITES_TRIGGER_KEEP)[0] == "rescue":
            print(f"\n[{lib['name']}: {folder}] {decide('Holding', None, HOLDING_DAYS, sig, FAVORITES_TRIGGER_KEEP)[1]} Rescue to Keep.")
            if move_or_report(lib, folder, path, lib["keep"]):
                if not DRY_RUN:
                    state["queued"].pop(key, None)
                    state["keep_seen"].setdefault(key, datetime.datetime.now().isoformat())
                record_action("rescue", folder, decide("Holding", None, HOLDING_DAYS, sig, FAVORITES_TRIGGER_KEEP)[1], lib["name"])
                sync_arr(lib, folder, lib["app_keep"], monitored=True, state=state, stage="keep")
            continue

        queued_at = state["queued"].get(key)
        if queued_at is None:
            queued_at = datetime.datetime.now().isoformat()
            if not DRY_RUN:
                state["queued"][key] = queued_at
        age = days_between(datetime.datetime.fromisoformat(queued_at))

        if decide("Holding", age, HOLDING_DAYS, sig, FAVORITES_TRIGGER_KEEP)[0] == "to_removal":
            print(f"\n[{lib['name']}: {folder}] In Holding {age}d, no favorite: move to Removal.")
            if move_or_report(lib, folder, path, lib["removal"]):
                if not DRY_RUN:
                    state["queued"].pop(key, None)
                    state["in_removal"][key] = datetime.datetime.now().isoformat()
                record_action("to_removal", folder, f"in Holding {age} days", lib["name"])
                sync_arr(lib, folder, lib["app_removal"], monitored=False, state=state, stage="removal")
        else:
            print(f"\n[{lib['name']}: {folder}] In Holding {age}d ({HOLDING_DAYS - age} days left to favorite it).")
            _holding_status.append({"library": lib["name"], "folder": folder, "days_left": HOLDING_DAYS - age})


def audit_transient(lib: dict, signals: dict, state: dict):
    folders = list_folders(lib["transient"])

    for folder in folders:
        path = os.path.join(lib["transient"], folder)

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
        if sig.get("protected"):
            note += f" (tagged {PROTECT_TAG})"
        print(f"\n[{lib['name']}: {folder}] age={age}d{note} played={sig['played']} "
              f"favorite={sig['favorite']} disliked={sig['disliked']}")

        # Priority 1: favorited (watched or not) -> keep
        if decide("Waiting", age, wait, sig, FAVORITES_TRIGGER_KEEP)[0] == "keep":
            print(f"-> {decide('Waiting', age, wait, sig, FAVORITES_TRIGGER_KEEP)[1]} Move to Keep.")
            if move_or_report(lib, folder, path, lib["keep"]):
                if not DRY_RUN:
                    state["first_seen"].pop(key, None)
                    state["keep_seen"].setdefault(key, datetime.datetime.now().isoformat())
                record_action("keep", folder, decide("Waiting", age, wait, sig, FAVORITES_TRIGGER_KEEP)[1], lib["name"])
                sync_arr(lib, folder, lib["app_keep"], state=state, stage="keep")
        # Priority 2: tagged not-at-all -> Holding right away
        elif decide("Waiting", age, wait, sig, FAVORITES_TRIGGER_KEEP)[0] == "hold" and sig["disliked"]:
            print("-> Tagged not-at-all: move to Holding.")
            move_to_holding(lib, folder, path, state, f"tagged {DISLIKE_TAG}")
        # Priority 3: still no decision after the waiting period -> Holding
        elif decide("Waiting", age, wait, sig, FAVORITES_TRIGGER_KEEP)[0] == "hold":
            print(f"-> No favorite after {wait}+ days: move to Holding.")
            move_to_holding(lib, folder, path, state, f"no favorite after {age} days")
        else:
            _stats["waiting"] += 1
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
    if not ALLOW_PERMANENT_DELETE:
        print("[PRUNE SKIPPED] Master permanent deletion switch is disabled.")
        return
    arr = lib["arr"]
    if not arr.enabled:
        print("[WARN] Season pruning needs Sonarr (SONARR_URL / SONARR_API_KEY); skipping.")
        return

    folders = list_folders(lib["keep"])
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
            print(f"{label} Protected by '{PROTECT_TAG}' or '{KEEP_ALL_SEASONS_TAG}': keeping all seasons.")
            continue
        if days_in_keep < SEASON_PRUNE_GRACE_DAYS:
            print(f"{label} In Keep {days_in_keep}d: no pruning for another "
                  f"{SEASON_PRUNE_GRACE_DAYS - days_in_keep} days (time to add the keep-all tag).")
            continue

        try:
            item = arr.find(folder)
            if not item:
                print(f"{label} Not found in Sonarr; skipping.")
                continue
            files = arr.episode_files(item)
        except (AmbiguousMatchError, requests.RequestException) as e:
            print(f"{label} Could not look it up in Sonarr ({type(e).__name__}); skipping.")
            continue

        by_season: Dict[int, List[dict]] = {}
        for f in files:
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
        try:
            arr.prune_seasons(item, old_seasons, old_files)
        except requests.RequestException as e:
            print(f"{label} Pruning failed ({type(e).__name__}).")
            record_action("prune_failed", folder, f"{arr.name} request failed ({type(e).__name__})",
                          lib["name"], status="failed")
            continue
        action_done()
        record_action("prune_seasons", folder,
                      f"deleted seasons {old_seasons} ({len(old_files)} files); kept season {latest}",
                      lib["name"])

    # Forget shows that have left the Keep folder
    for key in list(state["keep_seen"]):
        if key_belongs_to(lib, key) and key[len(lib["state_prefix"]):] not in folders:
            state["keep_seen"].pop(key, None)


# ==============================================
# --- RUN SUMMARY ---
# ==============================================

def print_run_summary():
    def count(action: str) -> int:
        return sum(1 for e in _events if e["action"] == action and e["status"] in ("done", "planned"))

    deleted = [e for e in _events if e["action"] == "delete" and e["status"] in ("done", "planned")]
    freed = sum(e.get("size_bytes", 0) for e in deleted)
    problems = sum(1 for e in _events if e["status"] in ("failed", "skipped"))

    header = "Run summary [DRY RUN - nothing was changed]" if DRY_RUN else "Run summary"
    rows = [
        ("Waiting in Transient", _stats["waiting"]),
        ("Favorites sent to Keep", count("keep")),
        ("Sent to Holding", count("hold")),
        ("Rescued from Holding", count("rescue")),
        ("Still in Holding", len(_holding_status)),
        ("Sent to Removal", count("to_removal")),
        ("Still in Removal", _stats["in_removal"]),
        ("Deleted" + (" (space freed)" if deleted else ""),
         f"{len(deleted)} ({human_size(freed)})" if deleted else 0),
        ("Seasons pruned", count("prune_seasons")),
    ]
    if problems:
        rows.append(("Problems (see the action log)", problems))
    print(f"\n=== {header} ===")
    for label, value in rows:
        print(f"  {label + ':':<34}{value}")


# ==============================================
# --- NOTIFICATIONS (optional) ---
# ==============================================

NOTIFY_HEADINGS = {
    "run_failed": "Run failed",
    "move_failed": "Could not move",
    "arr_sync_failed": "Radarr/Sonarr was not updated (fix by hand)",
    "delete_failed": "Delete failed",
    "delete_skipped": "Not deleted (needs your attention)",
    "prune_failed": "Season pruning failed",
    "hold": "Moved to Leaving Soon",
    "rescue": "Rescued to Keep",
    "to_removal": "Moved to Removal (last stop before deletion)",
    "delete": "Permanently deleted",
    "prune_seasons": "Old seasons removed",
    "cap_skipped": "Skipped (per-run action limit reached)",
}


def notifications_configured() -> bool:
    return bool(NOTIFY_DISCORD_WEBHOOK_URL or NOTIFY_NTFY_URL or NOTIFY_WEBHOOK_URL)


def build_notification() -> Optional[Dict[str, Any]]:
    """Summarize this run. Returns None when there is nothing worth a message."""
    events = [e for e in _events if e["action"] in NOTIFY_HEADINGS]
    leaving = list(_holding_status) if NOTIFY_LEAVING_SOON_DIGEST else []
    if not events and not leaving:
        return None

    lines: List[str] = []
    for action, heading in NOTIFY_HEADINGS.items():
        group = [e for e in events if e["action"] == action]
        if not group:
            continue
        total = sum(e.get("size_bytes", 0) for e in group)
        suffix = f", {human_size(total)}" if total else ""
        lines.append(f"{heading} ({len(group)}{suffix}):")
        for e in group:
            if action == "run_failed":
                lines.append(f"  - {e['detail']}")
            else:
                text = f"{e['library']}: {e['folder']}"
                lines.append(f"  - {text} - {e['detail']}" if e["detail"] else f"  - {text}")
        lines.append("")
    if leaving:
        lines.append(f"Leaving Soon - favorite in Jellyfin to keep ({len(leaving)}):")
        for item in sorted(leaving, key=lambda i: (i["days_left"], i["library"], i["folder"])):
            lines.append(f"  - {item['library']}: {item['folder']} ({max(item['days_left'], 0)} days left)")

    message = "\n".join(lines).strip()
    if len(message) > NOTIFY_MAX_CHARS:
        message = message[:NOTIFY_MAX_CHARS].rsplit("\n", 1)[0] + "\n...and more (see the action log)."
    return {
        "title": "Media Auditor" + (" [DRY RUN]" if DRY_RUN else ""),
        "message": message,
        "dry_run": DRY_RUN,
        "events": events,
        "leaving_soon": leaving,
    }


def _post(label: str, url: str, **kwargs) -> bool:
    """Send one notification. Never raises, and never prints the URL (webhook URLs are secrets)."""
    try:
        r = requests.post(url, timeout=15, **kwargs)
        r.raise_for_status()
        print(f"[NOTIFY] Sent via {label}.")
        return True
    except Exception as e:
        status = getattr(getattr(e, "response", None), "status_code", None)
        detail = f"{type(e).__name__}" + (f", HTTP {status}" if status else "")
        print(f"[NOTIFY ERROR] {label} failed ({detail}).")
        return False


def send_notification(note: Dict[str, Any]) -> bool:
    """Send to every configured target. Returns True only if all of them succeeded."""
    results = []
    if NOTIFY_DISCORD_WEBHOOK_URL:
        results.append(_post("Discord", NOTIFY_DISCORD_WEBHOOK_URL,
                             json={"content": f"**{note['title']}**\n{note['message']}"}))
    if NOTIFY_NTFY_URL:
        headers = {"Title": note["title"]}
        if NOTIFY_NTFY_TOKEN:
            headers["Authorization"] = f"Bearer {NOTIFY_NTFY_TOKEN}"
        results.append(_post("ntfy", NOTIFY_NTFY_URL, data=note["message"].encode("utf-8"), headers=headers))
    if NOTIFY_WEBHOOK_URL:
        results.append(_post("webhook", NOTIFY_WEBHOOK_URL, json=note))
    return bool(results) and all(results)


def send_run_notification():
    """Called at the end of a run (and when a run fails). Quiet during dry runs unless NOTIFY_ON_DRY_RUN."""
    if not notifications_configured():
        return
    if DRY_RUN and not NOTIFY_ON_DRY_RUN:
        return
    note = build_notification()
    if note:
        send_notification(note)


# ==============================================
# --- MAIN ---
# ==============================================

def refresh_jellyfin_after_audit():
    """Request an asynchronous Jellyfin scan after verified real media moves."""
    if not JELLYFIN_REFRESH_AFTER_AUDIT or DRY_RUN or _successful_media_moves == 0:
        return
    try:
        response = requests.post(
            f"{JELLYFIN_URL}/Library/Refresh",
            headers={"X-Emby-Token": JELLYFIN_TOKEN,
                     "Authorization": f'MediaBrowser Token="{JELLYFIN_TOKEN}"'},
            timeout=10,
            allow_redirects=False,
        )
        response.raise_for_status()
        if response.status_code >= 300:
            raise requests.HTTPError(f"Unexpected Jellyfin refresh status: {response.status_code}")
    except requests.RequestException as exc:
        print(f"[JELLYFIN REFRESH FAILED] {exc}")
        record_action("jellyfin_refresh_failed", "-", str(exc), "All", status="failed")
        return
    print(f"[JELLYFIN REFRESH] Requested library scan after {_successful_media_moves} successful media move(s).")
    record_action("jellyfin_refresh", "-", f"Requested scan after {_successful_media_moves} successful media move(s)", "All")


def run_once():
    """Run one audit under the same lock used by offline migration."""
    from state_lock import audit_run_lock
    from backend_selection import require_json_backend

    # Fail before creating directories, acquiring locks, or dispatching actions.
    require_json_backend(os.environ.get("AUDITOR_STATE_BACKEND", "json"))

    os.makedirs(os.path.dirname(os.path.abspath(STATE_FILE)), exist_ok=True)
    with audit_run_lock(STATE_FILE):
        return _run_once_locked()


def _run_once_locked():
    global _successful_media_moves
    _successful_media_moves = 0
    global _actions_taken
    _actions_taken = 0      # the action cap applies per run
    _events.clear()
    _holding_status.clear()
    _stats.update(waiting=0, in_removal=0)
    radarr.reset()          # re-read Radarr's / Sonarr's lists every run
    sonarr.reset()

    print("\n=== Media Collection Auditor ===")
    print(f"Run started {datetime.datetime.now().isoformat(timespec='seconds')}")
    print("DRY RUN: no changes will be made to your media." if DRY_RUN else "LIVE MODE: changes WILL be made.")

    if not JELLYFIN_TOKEN:
        raise SystemExit("[ERROR] JELLYFIN_API_TOKEN is not set.")

    libs = build_libraries()
    errors, warnings = preflight(libs)
    for warning in warnings:
        print(f"[PREFLIGHT WARNING] {warning}")
    if errors:
        for error in errors:
            print(f"[PREFLIGHT ERROR] {error}")
        raise SystemExit("[PREFLIGHT FAILED] Nothing was touched. " + " | ".join(errors))

    state = load_state()
    try:
        for lib in libs:
            print(f"\n----- {lib['name']} -----")
            signals = get_signals(lib["jellyfin_type"])
            reconcile_moved_titles(lib, state)
            reconcile_untracked_keep(lib, state)
            retry_pending_arr_sync(lib, state)
            audit_removal(lib, state, signals)      # block deletion when Jellyfin protection is unknown or active
            audit_holding(lib, signals, state)      # rescue favorites / move expired items to Removal
            audit_transient(lib, signals, state)    # keep favorites / move undecided items to Holding
            if lib.get("prune_seasons"):
                audit_keep_seasons(lib, signals, state)
    finally:
        save_state(state)   # even if the run stops half way, what already moved is remembered

    refresh_jellyfin_after_audit()
    record_action("run_complete", "-", f"{_actions_taken} hold/delete/prune actions this run", "All")
    print_run_summary()
    send_run_notification()


def run_with_alerts():
    """run_once(), but a failed run is recorded and reported before the error is passed on."""
    try:
        run_once()
    except (Exception, SystemExit) as e:
        print(f"[RUN FAILED] {e}")
        record_action("run_failed", "-", str(e)[:200], "All", status="failed")
        send_run_notification()
        raise


if __name__ == "__main__":
    if "--test-notify" in sys.argv:
        if not notifications_configured():
            raise SystemExit("No notification target set. Set NOTIFY_DISCORD_WEBHOOK_URL, NOTIFY_NTFY_URL "
                             "or NOTIFY_WEBHOOK_URL in your .env file.")
        ok = send_notification({"title": "Media Auditor test",
                                "message": "If you can read this, notifications are working.",
                                "dry_run": DRY_RUN, "events": [], "leaving_soon": []})
        raise SystemExit(0 if ok else 1)   # non-zero when any target failed, so a broken setup is obvious

    if RUN_INTERVAL_HOURS <= 0:
        run_with_alerts()
    else:
        print(f"Loop mode: running every {RUN_INTERVAL_HOURS} hours.")
        while True:
            try:
                run_with_alerts()
            except (Exception, SystemExit):
                # In loop mode an error (Jellyfin down, bad token, etc.) must not kill the
                # container, or Docker would restart it and hit the APIs again right away.
                pass
            print(f"Sleeping {RUN_INTERVAL_HOURS} hours until the next run.")
            time.sleep(RUN_INTERVAL_HOURS * 3600)
