"""Validate the saved media-library registry used by worker integrations."""

from dataclasses import dataclass
import json
import re

from app.filesystem_paths import _canonical
from app.json_validation import parse_unique_json


MAX_LIBRARIES = 16
_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _-]{0,63}\Z")


@dataclass(frozen=True)
class MediaLibrary:
    name: str
    media_type: str
    root: str

    @property
    def is_tv(self):
        return self.media_type == "tv"


def _validate_definition(item):
    if not isinstance(item, dict):
        raise ValueError("Each media library must be an object")
    name = item.get("name")
    media_type = item.get("type")
    root = item.get("root")
    if (not isinstance(name, str) or not _NAME.fullmatch(name)
            or not isinstance(media_type, str) or media_type not in ("movie", "tv")
            or not isinstance(root, str)):
        raise ValueError("Each media library requires a valid name, type, and root")
    try:
        root = _canonical(root)
    except ValueError:
        raise ValueError("Media library roots must be absolute canonical paths") from None
    if root == "/":
        raise ValueError("Media library roots must not be filesystem root")
    return MediaLibrary(name, media_type, root)


def parse_media_libraries(raw):
    """Parse a bounded JSON array of unique, non-overlapping library roots."""
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("Media library configuration is required")
    try:
        data = parse_unique_json(raw.encode("utf-8"))
    except (UnicodeEncodeError, ValueError):
        raise ValueError("Media library configuration must be valid JSON") from None
    if not isinstance(data, list) or not 1 <= len(data) <= MAX_LIBRARIES:
        raise ValueError(f"Media library configuration must contain one to {MAX_LIBRARIES} libraries")
    libraries = tuple(_validate_definition(item) for item in data)
    names = [library.name.casefold() for library in libraries]
    if len(set(names)) != len(names):
        raise ValueError("Media library names must be unique")
    for index, library in enumerate(libraries):
        for other in libraries[index + 1:]:
            if (library.root == other.root
                    or library.root.startswith(other.root + "/")
                    or other.root.startswith(library.root + "/")):
                raise ValueError("Media library roots must be distinct and non-overlapping")
    return libraries


def canonical_media_libraries(raw):
    """Return a stable JSON representation suitable for saved settings."""
    return json.dumps(
        [library.__dict__ for library in parse_media_libraries(raw)],
        separators=(",", ":"),
        sort_keys=True,
    )


def legacy_media_libraries(settings):
    """Build the compatibility registry from the existing Movies/TV settings."""
    base = _canonical(str(settings.get("MEDIA_PATH", "/media")).strip())
    libraries = []
    if str(settings.get("ENABLE_MOVIES", "true")).lower() == "true":
        libraries.append(MediaLibrary("Movies", "movie", base + "/Movies"))
    if str(settings.get("ENABLE_TV", "false")).lower() == "true":
        libraries.append(MediaLibrary("TV", "tv", base + "/TV"))
    if not libraries:
        raise ValueError("At least one media library must be enabled")
    return tuple(libraries)


def configured_media_libraries(settings):
    """Use the saved registry when present, otherwise preserve legacy behavior."""
    raw = settings.get("MEDIA_LIBRARIES", "")
    return parse_media_libraries(raw) if isinstance(raw, str) and raw.strip() else legacy_media_libraries(settings)


def library_stage_paths(settings, library):
    """Return local and Arr-visible stage roots for one configured library."""
    registered = configured_media_libraries(settings)
    definition = next((item for item in registered if item.name == library), None)
    if definition is None:
        raise ValueError("Unknown media library")
    if not settings.get("MEDIA_LIBRARIES", "").strip() and library in ("Movies", "TV"):
        prefix = "SONARR" if is_tv_library(library) else "RADARR"
        base = settings.get("MEDIA_PATH", "/media").strip()
        defaults = {
            "Waiting": "",
            "Holding": "_hold",
            "Keep": "_keep",
            "Removal": "_removal",
        }
        local = {}
        remote = {}
        for stage, suffix in defaults.items():
            field = {"Waiting": "TRANSIENT", "Holding": "HOLDING",
                     "Keep": "KEEP", "Removal": "REMOVAL"}[stage]
            local[stage] = _canonical(
                settings.get(prefix + "_" + field + "_PATH", "").strip()
                or base + "/" + library + suffix
            )
            alias = settings.get(prefix + "_APP_" + stage.upper() + "_PATH", "") if stage != "Waiting" else ""
            remote[stage] = _canonical(alias.strip() or local[stage])
        return definition, local, remote
    local = {
        "Waiting": definition.root,
        "Holding": definition.root + "_hold",
        "Keep": definition.root + "_keep",
        "Removal": definition.root + "_removal",
    }
    return definition, local, dict(local)


def is_tv_library(name, media_type=None):
    """Identify TV libraries while preserving the legacy name-only contract."""
    return media_type == "tv" or (media_type is None and name == "TV")


def media_key_for(name, folder, media_type=None):
    """Build a collision-free tracking key with legacy key compatibility."""
    if name == "Movies" and not is_tv_library(name, media_type):
        return folder
    if name == "TV" and is_tv_library(name, media_type):
        return "TV/" + folder
    return name + "/" + folder


def media_folder_for(name, media_key, media_type=None):
    """Extract a title folder from a library tracking key."""
    prefix = "" if name == "Movies" and not is_tv_library(name, media_type) else name + "/"
    if not isinstance(media_key, str) or not media_key.startswith(prefix):
        raise ValueError("Tracking key does not belong to library")
    folder = media_key[len(prefix):]
    if not folder or "/" in folder:
        raise ValueError("Tracking key must contain one title folder")
    return folder
