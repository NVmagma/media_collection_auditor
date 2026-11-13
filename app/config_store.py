import json
import os
from pathlib import Path
from typing import Dict, List

# ---- existing constants (unchanged) ---------------------------------------
JELLYFIN_URL = os.getenv('JELLYFIN_HOST_URL', 'http://localhost:8096')
# ... all the other legacy env vars ...

# ---- NEW: Dynamic library configuration ------------------------------------
DEFAULT_LIBRARIES = {
    'movies': '/media/movies',
    'tv':     '/media/tv'
}

def load_media_libraries() -> Dict[str, str]:
    """Read MEDIA_LIBRARIES env var (JSON string) or fall back to defaults."""
    raw = os.getenv('MEDIA_LIBRARIES')
    if not raw:
        return DEFAULT_LIBRARIES
    try:
        cfg = json.loads(raw)
        if not isinstance(cfg, dict):
            raise ValueError
    except Exception:
        from .log import logger  # pragma: no cover – defensive fallback
        logger.warning('MEDIA_LIBRARIES env var invalid; using defaults')
        return DEFAULT_LIBRARIES
    # Normalise: strip trailing slashes, enforce absolute paths.
    return {name.strip(): os.path.abspath(path.rstrip('/')) for name, path in cfg.items()}

MEDIA_LIBRARIES: Dict[str, str] = load_media_libraries()

def get_library_roots() -> List[str]:
    """Convenience for code that wants a simple list."""
    return list(MEDIA_LIBRARIES.values())

def get_library_name_by_path(path: str) -> str | None:
    """Return the library key that owns *path*, or None."""
    for name, root in MEDIA_LIBRARIES.items():
        if os.path.commonpath([root, path]) == root:
            return name
    return None

# Backward‑compatibility aliases – unchanged
MOVIES_ROOT = MEDIA_LIBRARIES.get('movies')
TV_ROOT     = MEDIA_LIBRARIES.get('tv')