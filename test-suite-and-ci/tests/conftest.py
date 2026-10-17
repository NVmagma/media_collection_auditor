"""Shared test setup.

Every test gets a throwaway media library in a temp folder, a freshly loaded copy of the script
configured to point at it, and a guard that fails the test if anything tries to use the network.
Nothing here touches your real media, state file, or API keys.
"""
import datetime
import importlib
import json
import os
import sys
import time

import pytest
import requests

# Tests live under test-suite-and-ci/, while the application lives in the repo-level app/ directory.
# Add the repository app directory explicitly so tests work from a clean checkout.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(REPO_ROOT, "app"))

# Every setting the script reads. Cleared before each test so a developer's real environment
# (or .env file) can never leak in and cause a test to talk to a real server.
SETTINGS = [
    "DRY_RUN", "JELLYFIN_HOST_URL", "JELLYFIN_API_TOKEN", "JELLYFIN_REFRESH_AFTER_AUDIT", "DISLIKE_TAG", "PROTECT_TAG",
    "RADARR_URL", "RADARR_API_KEY", "SONARR_URL", "SONARR_API_KEY",
    "ENABLE_MOVIES", "ENABLE_TV", "ENABLE_SEASON_PRUNING", "MEDIA_PATH", "STATE_FILE", "ACTION_LOG_FILE",
    "MOVIE_WAIT_DAYS", "TV_WAIT_DAYS", "HOLDING_DAYS", "REMOVAL_DAYS", "TV_NEW_EPISODES_RESET_CLOCK",
    "KEEP_ALL_SEASONS_TAG", "SEASON_PRUNE_GRACE_DAYS", "SEASON_PRUNE_AFTER_NEW_SEASON_DAYS",
    "MAX_ACTIONS_PER_RUN", "RUN_INTERVAL_HOURS", "ALLOW_PERMANENT_DELETE", "ALLOW_FILESYSTEM_DELETE", "ALLOW_CROSS_FILESYSTEM_MOVES",
    "NOTIFY_DISCORD_WEBHOOK_URL", "NOTIFY_NTFY_URL", "NOTIFY_NTFY_TOKEN", "NOTIFY_WEBHOOK_URL",
    "NOTIFY_ON_DRY_RUN", "NOTIFY_LEAVING_SOON_DIGEST",
] + [f"{p}_{k}_PATH" for p in ("RADARR", "SONARR") for k in ("TRANSIENT", "HOLDING", "KEEP", "REMOVAL")] \
  + [f"{p}_APP_{k}_PATH" for p in ("RADARR", "SONARR") for k in ("HOLDING", "KEEP", "REMOVAL")]


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Any real HTTP call in a test is a bug; fail loudly instead of reaching a real server."""
    def blocked(*args, **kwargs):
        raise AssertionError("A test tried to make a real network call")
    for name in ("get", "post", "put", "delete"):
        monkeypatch.setattr(requests, name, blocked)


class FakeResponse:
    status_code = 200

    def raise_for_status(self):
        pass


class PostRecorder:
    """Stands in for requests.post and remembers every call."""

    def __init__(self):
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return FakeResponse()


@pytest.fixture
def posts(monkeypatch):
    recorder = PostRecorder()
    monkeypatch.setattr(requests, "post", recorder)
    return recorder


def signal_flags(**flags):
    base = {"played": False, "favorite": False, "disliked": False, "keep_all": False, "protected": False}
    base.update(flags)
    return base


class Auditor:
    """A loaded copy of the script plus helpers for building and inspecting a fake library."""

    def __init__(self, ca, root):
        self.ca = ca
        self.root = root
        self.media = root / "media"
        self.logs = root / "logs"
        self.media.mkdir(exist_ok=True)
        self.signals = {"Movie": {}, "Series": {}}
        ca.get_signals = lambda jellyfin_type: self.signals[jellyfin_type]
        # The network half of the preflight is replaced by a "everything is reachable" stub so ordinary tests
        # need no fake servers; the real one is kept so the safety tests can exercise it.
        self.real_check_services = ca.check_services
        ca.check_services = lambda libs: ([], [])

    # --- building the library ---
    def add(self, library_folder, name, age_days=None):
        """Create <library_folder>/<name> containing one file. age_days backdates the file dates."""
        folder = self.media / library_folder / name
        folder.mkdir(parents=True)
        (folder / "video.mkv").write_text("x")
        if age_days is not None:
            self.backdate(folder, age_days)
        return folder

    def backdate(self, folder, days):
        stamp = time.time() - days * 86400
        for root, dirs, files in os.walk(folder):
            for entry in files + dirs:
                os.utime(os.path.join(root, entry), (stamp, stamp))
        os.utime(folder, (stamp, stamp))

    def movie(self, name, **flags):
        self.signals["Movie"][name] = signal_flags(**flags)

    def show(self, name, **flags):
        self.signals["Series"][name] = signal_flags(**flags)

    # --- running and inspecting ---
    def make_folders(self):
        """Create every folder the preflight requires (the script itself never creates them)."""
        for lib in self.ca.build_libraries():
            for kind in self.ca.FOLDER_KINDS:
                os.makedirs(lib[kind], exist_ok=True)

    def run(self):
        self.make_folders()
        self.ca.run_once()

    def where(self, name):
        """Name of the library folder currently holding <name>, or GONE."""
        for entry in sorted(os.listdir(self.media)):
            if (self.media / entry / name).is_dir():
                return entry
        return "GONE"

    def state(self):
        with open(self.logs / "auditor_state.json") as f:
            return json.load(f)

    def set_state(self, section, key, days_ago):
        state = self.state()
        state.setdefault(section, {})[key] = (datetime.datetime.now() - datetime.timedelta(days=days_ago)).isoformat()
        with open(self.logs / "auditor_state.json", "w") as f:
            json.dump(state, f)

    def actions(self, action=None):
        path = self.logs / "auditor_actions.jsonl"
        if not path.exists():
            return []
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        return [r for r in rows if action is None or r["action"] == action]


@pytest.fixture
def make_auditor(tmp_path, monkeypatch):
    """Factory: make_auditor(DRY_RUN="true", ENABLE_TV="true", ...) returns a ready Auditor."""
    def _make(**overrides):
        for name in SETTINGS:
            monkeypatch.delenv(name, raising=False)
        env = {
            "DRY_RUN": "false",
            "JELLYFIN_API_TOKEN": "test-token",
            "MEDIA_PATH": str(tmp_path / "media"),
            # Most tests are about timers and decisions with no Radarr/Sonarr involved, so the script
            # may delete folders itself. The safety tests switch this off to check the real default.
            "ALLOW_FILESYSTEM_DELETE": "true",
            # Disposable-media behavioral tests explicitly opt into the new master gate.
            # Production remains default-deny; dedicated safety tests verify that default.
            "ALLOW_PERMANENT_DELETE": "true",
            "STATE_FILE": str(tmp_path / "logs" / "auditor_state.json"),
            "ACTION_LOG_FILE": str(tmp_path / "logs" / "auditor_actions.jsonl"),
        }
        env.update({k: str(v) for k, v in overrides.items()})
        for key, value in env.items():
            monkeypatch.setenv(key, value)
        monkeypatch.setattr("dotenv.load_dotenv", lambda *args, **kwargs: False)
        import collection_auditor
        ca = importlib.reload(collection_auditor)
        return Auditor(ca, tmp_path)
    return _make
