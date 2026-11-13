import pathlib
from .config_store import MEDIA_LIBRARIES

def scan_root(root: str):
    """Return a list of *file* Paths under `root` (recursively)."""
    return [p for p in pathlib.Path(root).rglob('*') if p.is_file()]

def collect_all_media():
    """Return a mapping: library_name → list of file Paths."""
    all_media = {}
    for name, root in MEDIA_LIBRARIES.items():
        all_media[name] = scan_root(root)
    return all_media