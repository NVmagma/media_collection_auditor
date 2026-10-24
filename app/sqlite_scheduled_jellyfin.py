"""Uncached collector adapter for per-candidate scheduled protection reads.

The transport must perform read-only authoritative requests with bounded network
operations. This module neither supplies credentials nor authorizes execution.
Existing collector ambiguity/coverage checks remain mandatory.
"""
from copy import deepcopy
from datetime import datetime

from app.sqlite_jellyfin_collection import collect_title_observation
from app.sqlite_scheduled_plan import PlannedMove
from app.sqlite_scheduled_recheck import ProtectionRead
from app.sqlite_title_identity import validate_title_folder


def scheduled_protection_provider(*, fetch, bindings, clock=datetime.now):
    """Bind media keys to (single folder, Movie|Series), never scan-time signals.

    Default tag names follow the existing collector. Custom tag configuration
    is not supported by this adapter and must not be silently routed through it.
    """
    if not callable(fetch) or not isinstance(bindings, dict) or not bindings:
        raise ValueError('Read-only transport and explicit title bindings required')
    captured = deepcopy(bindings)
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
            folder=folder, media_key=move.media_key, now=clock())
        if observation['status'] != 'shape_valid_untrusted' or observation['blockers']:
            return ProtectionRead(False, None)
        return ProtectionRead(True, deepcopy(observation['signals']))
    return read
