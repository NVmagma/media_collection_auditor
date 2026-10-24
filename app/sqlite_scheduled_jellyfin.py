"""Uncached collector adapter for per-candidate scheduled protection reads.

The transport must perform read-only authoritative requests with bounded network
operations. This module neither supplies credentials nor authorizes execution.
Existing collector ambiguity/coverage checks remain mandatory.
"""
from copy import deepcopy
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


def scheduled_inventory_signal_reader(*, fetch, clock=datetime.now, tag_names=None):
    """Fresh scan-time signals for the worker's immutable inventory bindings.

    This reader is separate from the per-move provider; a future executor must
    still repeat protection collection immediately before each move.
    """
    from app.sqlite_scheduled_worker import ScheduledTitleBinding
    if not callable(fetch):
        raise ValueError('Read-only transport required')
    tags = validated_tag_names(tag_names)
    def read(binding):
        if (not isinstance(binding, ScheduledTitleBinding)
                or binding.jellyfin_type not in ('Movie', 'Series')
                or binding.media_key != (binding.folder if binding.jellyfin_type == 'Movie'
                                          else 'TV/' + binding.folder)):
            raise ValueError('Worker inventory identity mismatch')
        validate_title_folder(binding.folder)
        observation = collect_title_observation(fetch=fetch, jellyfin_type=binding.jellyfin_type,
            folder=binding.folder, media_key=binding.media_key, now=clock(), tag_names=tags)
        if observation['status'] != 'shape_valid_untrusted' or observation['blockers']:
            return None
        return deepcopy(observation['signals'])
    return read
