"""Cache Jellyfin GET results for one scan. Do not use this cache for final move checks."""
from copy import deepcopy
import json

class _ScanCatalog:
    """Keep separate copies of GET results within the limits for one scan, never for final move checks."""
    def __init__(self, fetch, maximum_bytes=64 * 1024 * 1024):
        self.fetch = fetch
        self.maximum_bytes = maximum_bytes
        self.reset()

    def reset(self):
        self.pages = {}
        self.size = 0
        self.failed = False

    def __call__(self, path, params):
        if self.failed:
            raise RuntimeError('Scan catalog unavailable')
        key = (path, tuple(sorted(params.items())) if params is not None else None)
        if key not in self.pages:
            try:
                value = self.fetch(path, params)
                size = len(json.dumps(value, allow_nan=False).encode('utf-8'))
                if len(self.pages) >= 10000 or self.size + size > self.maximum_bytes:
                    raise RuntimeError('Scan catalog limit exceeded')
                self.pages[key] = deepcopy(value)
                self.size += size
            except Exception:
                self.failed = True
                self.pages.clear()
                raise
        return deepcopy(self.pages[key])
