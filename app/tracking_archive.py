"""Archive one reviewed stale clock while holding the worker lock."""
from datetime import datetime, timezone
from pathlib import Path
import hmac
import json
import os

from app.filesystem_paths import _open_directory, scan_held_directory
from app.json_scan_control import _control
from app.json_tracking_store import JsonTrackingStore
from app.json_worker_cycle import stage_paths
from app.tracking_review import SECTIONS, _fold, _identity, _title
from app.tracking_schema import has_pending_extension

ARCHIVE = 'archived_tracking_clocks'


def _absence(roots, title):
    observed = {}
    folded = _fold(title)
    for stage, path in roots.items():
        fd = _open_directory(path)
        try:
            def identity(info):
                return info.st_dev, info.st_ino, info.st_mtime_ns, info.st_ctime_ns

            before = identity(os.fstat(fd))
            with scan_held_directory(fd) as entries:
                for count, entry in enumerate(entries, 1):
                    if count > 10000 or _fold(entry.name) == folded:
                        raise RuntimeError('Folder absence could not be verified')
            if identity(os.fstat(fd)) != before:
                raise RuntimeError('Directory changed during review')
            observed[stage] = before
        finally:
            os.close(fd)
    if len({value[:2] for value in observed.values()}) != len(roots):
        raise RuntimeError('Stage directories are aliased')
    return observed


def review_clock(*, library, title, settings, signing_key, expected=None):
    """Return a preview, or archive only when a fresh preview still matches."""
    if library not in ('Movies', 'TV') or _title(title).startswith('.'):
        raise ValueError('Invalid tracking selection')
    captured = settings()
    enabled = 'ENABLE_TV' if library == 'TV' else 'ENABLE_MOVIES'
    if captured.get(enabled, 'false' if library == 'TV' else 'true') != 'true':
        raise ValueError('Library disabled')
    roots, _ = stage_paths(captured, library)
    paths = list(map(Path, roots.values()))
    if any(a == b or a in b.parents or b in a.parents
           for i, a in enumerate(paths) for b in paths[i + 1:]):
        raise ValueError('Stage roots overlap')
    key = 'TV/' + title if library == 'TV' else title
    store = JsonTrackingStore(captured.get('STATE_FILE', '/app/logs/auditor_state.json'))
    with store.session() as session:
        state = session.state
        if (_control(state)['journal'] is not None or state['arr_sync_pending']
                or has_pending_extension(state)):
            raise RuntimeError('Operation recovery required')
        clocks = [(stage, section, state[section][key]) for stage, section in SECTIONS.items()
                  if key in state[section]]
        archive = state.get(ARCHIVE, {})
        if len(clocks) != 1 or not isinstance(archive, dict) or key in archive:
            raise RuntimeError('Clock requires separate review')
        stage, section, timestamp = clocks[0]
        observed = _absence(roots, title)
        payload = json.dumps([captured, observed, session._identity, library, title, stage, timestamp],
                             sort_keys=True, ensure_ascii=True).encode()
        fingerprint = hmac.digest(signing_key, payload, 'sha256').hex()
        if expected is not None and not hmac.compare_digest(fingerprint, expected):
            raise RuntimeError('Review changed')
        if _absence(roots, title) != observed or settings() != captured:
            raise RuntimeError('Review sources changed')
        session.verify()
        if expected is not None:
            state.setdefault(ARCHIVE, {})[key] = {
                'stage': stage, 'timestamp': timestamp,
                'archived_at': datetime.now(timezone.utc).isoformat(),
            }
            del state[section][key]
            session.checkpoint()
        return {'stage': stage, 'timestamp': timestamp, 'fingerprint': fingerprint}


def archive_history(state, library, query, page):
    archive = state.get(ARCHIVE, {})
    if not isinstance(archive, dict):
        raise ValueError('Invalid clock archive')
    rows = []
    for key, entry in archive.items():
        name, title = _identity(key)
        if (not isinstance(entry, dict) or not isinstance(entry.get('stage'), str)
                or entry['stage'] not in SECTIONS
                or not all(isinstance(entry.get(field), str) for field in ('timestamp', 'archived_at'))):
            raise ValueError('Invalid archived clock')
        timestamp = datetime.fromisoformat(entry['timestamp'])
        archived_at = datetime.fromisoformat(entry['archived_at'])
        if timestamp.tzinfo is not None or archived_at.tzinfo is None:
            raise ValueError('Invalid archived timestamp')
        if (library == 'all' or name == library) and _fold(query) in _fold(title):
            rows.append({'library': name, 'title': title, 'stage': entry['stage'],
                         'timestamp': entry['timestamp'], 'archived_at': archived_at.astimezone(timezone.utc)})
    rows.sort(key=lambda row: (row['library'], _fold(row['title']), row['title']))
    rows.sort(key=lambda row: row['archived_at'], reverse=True)
    pages = max(1, (len(rows) + 24) // 25)
    page = min(page, pages)
    return {'rows': rows[(page - 1) * 25:page * 25], 'page': page, 'pages': pages,
            'matched': len(rows)}
