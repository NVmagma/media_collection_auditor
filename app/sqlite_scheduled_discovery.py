"""Pure scheduled discovery/reset clock proposals; no persistence or media I/O.

Proposals require a complete worker inventory. They cannot authorize a move or
replace the future worker's CAS checkpoint and post-checkpoint plan rebuild.
"""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime

from app.sqlite_lifecycle_checkpoint_plan import CLOCKS
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_scheduled_worker import ScheduledTitleBinding
from app.sqlite_state import validate_snapshot
from app.sqlite_title_identity import validate_title_folder


@dataclass(frozen=True)
class DiscoveryClockProposal:
    source_revision: int
    source_snapshot: dict
    proposed_snapshot: dict
    changes: tuple
    authorization: str = 'not_authorized'


def propose_discovery_clocks(*, snapshot, revision, bindings, now,
                             available_protection_keys, reset_content_times=None, reset_keys=frozenset()):
    """Initialize clocks at observation time, never infer old age from disk.

    Only titles with complete protection coverage can be initialized. Existing
    stage conflicts block the whole proposal; missing titles' clocks are retained.
    TV Waiting resets require explicit complete content observations (None means
    a verified empty directory). The caller must supply every enabled reset key;
    omission must never be used as a fallback for a failed content observation.
    """
    source = deepcopy(snapshot)
    validate_snapshot(source)
    if (type(revision) is not int or revision < 0 or INTENTS_KEY in source
            or not isinstance(now, datetime) or now.tzinfo is not None or now > datetime.now()
            or not isinstance(bindings, (tuple, list))
            or not isinstance(available_protection_keys, (set, frozenset))):
        raise ValueError('Complete inventory, clean tracking and observation time required')
    reset_times = deepcopy({} if reset_content_times is None else reset_content_times)
    if (not isinstance(reset_times, dict) or not isinstance(reset_keys, (set, frozenset))
            or set(reset_times) != reset_keys):
        raise ValueError('Explicit completed content observations required')
    indexed = {}
    for binding in bindings:
        if (not isinstance(binding, ScheduledTitleBinding) or binding.stage not in CLOCKS
                or binding.jellyfin_type not in ('Movie', 'Series')
                or binding.media_key != (binding.folder if binding.jellyfin_type == 'Movie'
                                          else 'TV/' + binding.folder)
                or binding.media_key in indexed):
            raise ValueError('Unique bound title inventory required')
        validate_title_folder(binding.folder)
        indexed[binding.media_key] = binding
    if not available_protection_keys.issubset(indexed) or not set(reset_times).issubset(indexed):
        raise ValueError('Clock observation identity mismatch')
    proposed = deepcopy(source); changes = []
    for key, binding in indexed.items():
        section = CLOCKS[binding.stage]
        existing = [clock for clock in CLOCKS.values() if key in source[clock]]
        if existing and existing != [section]:
            raise RuntimeError('Discovery stage conflicts with tracking; explicit review required')
        if key in reset_times:
            content_at = reset_times[key]
            if (binding.jellyfin_type != 'Series' or binding.stage != 'Waiting'
                    or (content_at is not None and (not isinstance(content_at, datetime)
                        or content_at.tzinfo is not None or content_at > now))):
                raise ValueError('Invalid TV waiting content observation')
        if key not in available_protection_keys:
            continue
        if not existing:
            proposed[section][key] = now.isoformat()
            changes.append((key, 'discovered', section))
        elif key in reset_times and reset_times[key] is not None:
            content_at = reset_times[key]
            if content_at > datetime.fromisoformat(source[section][key]):
                proposed[section][key] = content_at.isoformat()
                changes.append((key, 'content_reset', section))
    validate_snapshot(proposed)
    return DiscoveryClockProposal(revision, source, proposed, tuple(changes))
