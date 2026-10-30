"""Scan-scoped catalogs and uncached per-candidate protection reads.

The transport must perform read-only authoritative requests with bounded network
operations. This module neither supplies credentials nor authorizes execution.
Existing collector ambiguity/coverage checks remain mandatory.
"""
from copy import deepcopy
import json
from datetime import datetime

from app.sqlite_jellyfin_collection import collect_title_observation, validated_tag_names
from app.sqlite_scheduled_plan import PlannedMove
from app.sqlite_scheduled_recheck import ProtectionRead
from app.sqlite_title_identity import validate_title_folder


def scheduled_protection_provider(*, fetch, bindings, clock=datetime.now, tag_names=None):
    """Bind media keys to (single folder, Movie|Series), never scan-time signals.

    Tag names are validated and detached at construction. Worker integration
    must supply the configured mapping instead of silently using defaults.
    """
    if not callable(fetch) or not isinstance(bindings, dict) or not bindings:
        raise ValueError('Read-only transport and explicit title bindings required')
    captured = deepcopy(bindings)
    tags = validated_tag_names(tag_names)
    for key, binding in captured.items():
        if not isinstance(binding, tuple) or len(binding) != 2:
            raise ValueError('Folder and Jellyfin type binding required')
        folder, kind = binding
        validate_title_folder(folder)
        if kind not in ('Movie', 'Series') or key != (folder if kind == 'Movie' else 'TV/' + folder):
            raise ValueError('Media identity/type binding mismatch')
    def read(move):
        if not isinstance(move, PlannedMove) or move.media_key not in captured:
            return ProtectionRead(False, None)
        folder, kind = captured[move.media_key]
        observation = collect_title_observation(fetch=fetch, jellyfin_type=kind,
            folder=folder, media_key=move.media_key, now=clock(), tag_names=tags)
        if observation['status'] != 'shape_valid_untrusted' or observation['blockers']:
            return ProtectionRead(False, None)
        return ProtectionRead(True, deepcopy(observation['signals']))
    return read


def scheduled_inventory_signal_reader(*, fetch, clock=datetime.now, tag_names=None, share_catalog=False):
    """Fresh scan-time signals for the worker's immutable inventory bindings.

    This reader is separate from the per-move provider; a future executor must
    still repeat protection collection immediately before each move.
    """
    from app.sqlite_scheduled_worker import ScheduledTitleBinding
    if not callable(fetch):
        raise ValueError('Read-only transport required')
    tags = validated_tag_names(tag_names)
    if type(share_catalog) is not bool:
        raise ValueError('Explicit scan catalog selection required')
    catalog = _ScanCatalog(fetch) if share_catalog else None
    scan_fetch = catalog if catalog is not None else fetch
    def read(binding):
        if (not isinstance(binding, ScheduledTitleBinding)
                or binding.jellyfin_type not in ('Movie', 'Series')
                or binding.media_key != (binding.folder if binding.jellyfin_type == 'Movie'
                                          else 'TV/' + binding.folder)):
            raise ValueError('Worker inventory identity mismatch')
        validate_title_folder(binding.folder)
        observation = collect_title_observation(fetch=scan_fetch, jellyfin_type=binding.jellyfin_type,
            folder=binding.folder, media_key=binding.media_key, now=clock(), tag_names=tags)
        if observation['status'] != 'shape_valid_untrusted' or observation['blockers']:
            return None
        return deepcopy(observation['signals'])
    if catalog is not None:
        read.begin_scan = catalog.reset
    return read


class _ScanCatalog:
    """Bounded detached GET responses for one inventory pass, never move checks."""
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
