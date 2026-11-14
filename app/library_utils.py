def is_tv_library(name: str) -> bool:
    """Return True if the library key represents a TV collection."""
    return 'tv' in name.lower() or 'series' in name.lower()
