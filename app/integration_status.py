"""Offline, redacted status contract; no network endpoint or action authority."""
from app.tracking_schema import has_pending_extension
from datetime import datetime, timezone, timedelta
import os
from config_store import setting
if __package__:
    from .dashboard_tracking_snapshot import read_json_dashboard_snapshot
else:
    from dashboard_tracking_snapshot import read_json_dashboard_snapshot


def read_tracking_status(path):
    return _project_tracking_status(lambda: read_json_dashboard_snapshot(path, require_existing=True))


def _project_tracking_status(capture):
    """Capture authoritative JSON once; counts are records, not live inventory.

    Missing state is unavailable even though the legacy dashboard permits a
    fresh installation's missing file. Unknown extension values never escape.
    """
    report = {
        "schema_version": 1, "status": "unavailable", "read_only": True,
        "storage_authority": "json", "production_activation": "disabled",
        "production_authorized": False, "freshness_verified": False,
        "count_basis": "tracking_records", "tracking_counts": None,
        "pending_operation_present": None,
    }
    try:
        state = capture().state
    except RuntimeError:
        return report
    report.update(
        status="advisory_only",
        tracking_counts={name: len(state.get(section, {})) for name, section in (
            ("waiting", "first_seen"), ("holding", "queued"),
            ("keep", "keep_seen"), ("removal", "in_removal"),
            ("arr_sync_pending", "arr_sync_pending"))},
        pending_operation_present=(has_pending_extension(state) or bool(state.get('arr_sync_pending'))
            or isinstance(state.get('json_worker_control'),dict) and state['json_worker_control'].get('journal') is not None),
    )
    return report


def audit_status_report(current):
    """Project coordinator observations onto a fixed schema, never free text.

    Coordinator history reads are best effort; this is not durable-history or
    collector-health verification, even when a prior result says completed.
    """
    report = {"schema_version": 1, "status": "unavailable", "read_only": True,
              "production_activation": "disabled", "production_authorized": False,
              "freshness_verified": False, "source": "coordinator_snapshot",
              "running": None, "queued": None, "rescuing": None,
              "last_result": None, "last_started": None, "last_finished": None,
              "next_run": None}
    flags = ("running", "queued", "rescuing")
    if not isinstance(current, dict) or any(type(current.get(key)) is not bool for key in flags):
        return report
    report.update(status="advisory_only", **{key: current[key] for key in flags})
    result = current.get("last_result")
    if isinstance(result, str) and result in ("completed", "failed"):
        report["last_result"] = result
    for key in ("last_started", "last_finished", "next_run"):
        value = current.get(key)
        if not isinstance(value, str) or len(value) > 64:
            continue
        try:
            parsed = datetime.fromisoformat(value)
            if parsed.tzinfo is not None:
                report[key] = parsed.astimezone(timezone.utc).isoformat()
        except (ValueError, OverflowError):
            pass
    return report


def read_tracking_titles(path, view, *, holding_days=7, library=None):
    return _project_tracking_titles(lambda: read_json_dashboard_snapshot(path, require_existing=True),
                                    view, holding_days=holding_days, library_filter=library)


def _project_tracking_titles(capture, view, *, holding_days=7, library_filter=None):
    """Bounded opt-in title projection from one JSON read, without collection.

    Legacy timestamps are local wall time without an offset. Preserve that
    meaning rather than inventing UTC, elapsed seconds or a deletion deadline.
    """
    report = {"schema_version": 1, "status": "unavailable", "read_only": True,
              "production_activation": "disabled", "production_authorized": False,
              "storage_authority": "json", "freshness_verified": False,
              "count_basis": "tracking_records", "view": view, "limit": 10,
              "timestamp_basis": "legacy_local_wall_time", "items": None,
              "total_records": None, "truncated": None}
    if view not in ("oldest-waiting", "leaving-soon"):
        raise ValueError("Unknown title view")
    if library_filter not in (None, 'Movies', 'TV'):
        raise ValueError('Unknown library filter')
    if library_filter is not None: report['library_filter'] = library_filter
    try:
        if type(holding_days) is not int or not 1 <= holding_days <= 36500:
            return report
        state = capture().state
        section = "first_seen" if view == "oldest-waiting" else "queued"
        entries = []
        for key, value in state.get(section, {}).items():
            # first_seen can remain present after a title enters another stage.
            if view == "oldest-waiting" and any(
                    key in state.get(other, {}) for other in ("queued", "keep_seen", "in_removal")):
                continue
            library = "TV" if key.startswith("TV/") else "Movies"
            if library_filter is not None and library != library_filter:
                continue
            title = key[3:] if library == "TV" else key
            # State extensions or malformed keys must never leak raw paths.
            if (not title or len(title) > 250 or title in (".", "..")
                    or any(c in title for c in ("/", "\\"))
                    or any(ord(c) < 32 or ord(c) == 127 for c in title)):
                return report
            since = datetime.fromisoformat(value)
            estimate = since + timedelta(days=holding_days) if view == "leaving-soon" else None
            entries.append((since, library, title, {
                "title": title, "library": library,
                "stage": "waiting" if view == "oldest-waiting" else "holding",
                "since": since.isoformat(),
                "estimated_removal_stage_at": estimate.isoformat() if estimate else None,
                "transition_authorized": False,
            }))
        entries.sort(key=lambda entry: entry[:3])
    except (RuntimeError, ValueError, TypeError, OverflowError):
        return report
    report.update(status="advisory_only", items=[entry[3] for entry in entries[:10]],
                  total_records=len(entries), truncated=len(entries) > 10)
    return report


def collect_widget_media_index(fetch, media_type):
    """Bounded, complete per-user catalog for presentation, never protections.

    The caller supplies a deadline-bound GET transport. Folder matches are exact;
    display-name/year fallbacks and first-match selection are intentionally absent.
    """
    import posixpath
    import re
    if media_type not in ('Movie', 'Series'):
        raise ValueError('Unsupported widget media type')
    users = fetch('/Users', None)
    if not isinstance(users, list) or not 1 <= len(users) <= 32:
        raise ValueError('Invalid users')
    ids = [u.get('Id') if isinstance(u, dict) else None for u in users]
    valid_id = lambda value: isinstance(value, str) and re.fullmatch(r'[0-9a-fA-F]{32}', value) is not None
    if any(not valid_id(uid) for uid in ids):
        raise ValueError('Invalid user identities')
    ids = [uid.lower() for uid in ids]
    if len(set(ids)) != len(ids):
        raise ValueError('Duplicate user identities')
    folders = {}
    identities = {}
    requests_left = 64
    for uid in ids:
        start, expected, seen = 0, None, set()
        while True:
            requests_left -= 1
            if requests_left < 0:
                raise ValueError('Widget catalog bound exceeded')
            page = fetch('/Users/' + uid + '/Items', {
                'Recursive': 'true', 'IncludeItemTypes': media_type,
                'ExcludeItemTypes': 'BoxSet', 'CollapseBoxSetItems': 'false', 'Fields': 'Path',
                'EnableImages': 'true', 'StartIndex': start, 'Limit': 100})
            if not isinstance(page, dict):
                raise ValueError('Invalid page')
            total, items = page.get('TotalRecordCount'), page.get('Items')
            if (type(total) is not int or not 0 <= total <= 5000
                    or not isinstance(items, list)
                    or len(items) != min(100, max(0, total - start))
                    or (expected is not None and expected != total)
                    or ('StartIndex' in page and (type(page['StartIndex']) is not int or page['StartIndex'] != start))):
                raise ValueError('Incomplete widget catalog')
            expected = total
            for item in items:
                if not isinstance(item, dict) or not valid_id(item.get('Id')):
                    raise ValueError('Invalid item identity')
                item_id = item['Id'].lower()
                if item_id in seen:
                    raise ValueError('Repeated item')
                seen.add(item_id)
                if item.get('Type') == 'BoxSet':
                    continue
                path = item.get('Path')
                if (item.get('Type') != media_type or not isinstance(path, str)
                        or not path or any(ord(c) < 32 for c in path)):
                    raise ValueError('Invalid item fields')
                path = path.replace('\\', '/').rstrip('/')
                if not (path.startswith('/') or re.match(r'^[A-Za-z]:/', path)):
                    raise ValueError('Relative item path')
                if any(part in ('.', '..') for part in path.split('/')):
                    raise ValueError('Invalid item path')
                folder = posixpath.basename(posixpath.dirname(path) if media_type == 'Movie' else path)
                if not folder:
                    raise ValueError('Missing item folder')
                identity = (item_id, path)
                if item_id in identities and identities[item_id] != path:
                    raise ValueError('Conflicting item identity')
                identities[item_id] = path
                tags = item.get('ImageTags')
                has_poster = isinstance(tags, dict) and isinstance(tags.get('Primary'), str) and bool(tags['Primary'])
                matches = folders.setdefault(folder, {})
                matches[identity] = matches.get(identity, False) or has_poster
            start += len(items)
            if start == total:
                break
    return folders


def widget_media_base(value):
    """Accept an explicit HTTP(S) browser/transport base with no URL credentials."""
    import re
    from urllib.parse import urlsplit
    try:
        if (not isinstance(value, str) or any(ord(c) <= 32 or ord(c) >= 127 for c in value)
                or "\\" in value or "?" in value or "#" in value):
            return None
        base = value.rstrip('/')
        url = urlsplit(base)
        if (url.scheme not in ('http', 'https') or not url.hostname or not url.netloc
                or url.username is not None or url.password is not None or url.query or url.fragment
                or '%' in url.netloc
                or not re.fullmatch(r'(?:/[A-Za-z0-9_~-]+(?:\.[A-Za-z0-9_~-]+)*)*', url.path)):
            return None
        _ = url.port
        return base
    except ValueError:
        return None


def widget_media_urls(item, index, public_base):
    """Credential-free URLs only for one exact folder identity in a full catalog."""
    import re
    result = {'match_status': 'unavailable', 'poster_url': None, 'jellyfin_url': None}
    try:
        base = widget_media_base(public_base)
        if not base:
            return result
        if index is None:
            return result
        matches = index.get(item['title'], {})
        if len(matches) != 1:
            result['match_status'] = 'ambiguous' if matches else 'unmatched'
            return result
        (item_id, _path), has_poster = next(iter(matches.items()))
        if not re.fullmatch(r'[0-9a-f]{32}', item_id):
            return result
        result.update(match_status='matched',
                      jellyfin_url=base + '/web/index.html#!/details?id=' + item_id,
                      poster_url=(base + '/Items/' + item_id + '/Images/Primary?maxWidth=160&quality=80') if has_poster else None)
    except (ValueError, TypeError, KeyError):
        pass
    return result


def _unavailable():
    raise RuntimeError('Selected tracking source unavailable')






def _selected_report(path,view,holding_days,library=None):
    options={} if library is None else {'library':library}
    if os.environ.get('AUDITOR_STATE_BACKEND','json') == 'json':
        return read_tracking_status(path) if view=='summary' else read_tracking_titles(path,view,holding_days=holding_days,**options)
    report=(_project_tracking_status(_unavailable) if view=='summary' else
            _project_tracking_titles(_unavailable,view,holding_days=holding_days,library_filter=library))
    return {**report,'storage_authority':'unavailable','state_revision':None}


def read_selected_tracking_status(path):
    return _selected_report(path, 'summary', 7)


def read_selected_tracking_titles(path, view, *, holding_days=7, library=None):
    if view not in ('oldest-waiting', 'leaving-soon'):
        raise ValueError('Unknown title view')
    return _selected_report(path, view, holding_days, library)


def read_selected_dashboard_state(path):
    from app.backend_selection import require_json_backend
    require_json_backend(os.environ.get('AUDITOR_STATE_BACKEND','json'))
    return read_json_dashboard_snapshot(path,require_existing=os.environ.get('AUDITOR_WORKER_MODE')=='json_serialized').state




def selected_run_snapshot(legacy_snapshot):
    if os.environ.get('AUDITOR_STATE_BACKEND','json')!='json': return {**audit_status_report(None),'storage_authority':'unavailable'}
    if os.environ.get('AUDITOR_WORKER_MODE')=='json_serialized':
        from app.json_worker_service import SERVICE
        return SERVICE.report()
    return legacy_snapshot()


def selected_audit_status_report(legacy_snapshot):
    if os.environ.get('AUDITOR_STATE_BACKEND','json')!='json': return {**audit_status_report(None),'storage_authority':'unavailable'}
    if os.environ.get('AUDITOR_WORKER_MODE')=='json_serialized':
        from app.json_worker_service import SERVICE
        return SERVICE.report()
    try: current=legacy_snapshot()
    except (OSError,UnicodeError,ValueError,TypeError,RuntimeError): current=None
    return audit_status_report(current)


def selected_run_history(legacy_history,limit=100):
    if os.environ.get('AUDITOR_STATE_BACKEND','json')!='json': return []
    if os.environ.get('AUDITOR_WORKER_MODE')=='json_serialized':
        from app.json_worker_service import SERVICE
        return SERVICE.history(limit)
    return legacy_history(limit)


def read_selected_coverage(path, build):
    """Project bounded aggregate inventory while verifying the selected snapshot.

    The callback receives detached tracking only. Never return its source payload.
    JSON reads are checked before and after local inventory.
    """
    backend = os.environ.get('AUDITOR_STATE_BACKEND', 'json')
    if backend != 'json':
        raise RuntimeError('Unsupported tracking backend')
    if __package__:
        from .dashboard_tracking_snapshot import read_json_dashboard_snapshot
    else:
        from dashboard_tracking_snapshot import read_json_dashboard_snapshot
    from pathlib import Path
    import stat
    source = Path(path)
    before = source.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
        raise RuntimeError('Tracking source unavailable')
    capture = read_json_dashboard_snapshot(source, require_existing=True)
    state = capture.state
    report = build(state)
    after = source.lstat()
    if ((before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            or read_json_dashboard_snapshot(source, require_existing=True).state != state):
        raise RuntimeError('Tracking changed during observation')
    return {**report, 'storage_authority':'json', 'state_revision':None}


def selected_scan_capture():
    if os.environ.get('AUDITOR_WORKER_MODE')=='json_serialized' and os.environ.get('AUDITOR_STATE_BACKEND','json')=='json':
        from app.json_worker_service import SERVICE
        return {'run':SERVICE.report(),'history':SERVICE.history()}
    return None


def project_scan_capture(capture):
    """Fixed safe presentation contract shared by history and proposal APIs."""
    if __package__:
        from .dashboard_tracking_snapshot import build_scan_view
    else:
        from dashboard_tracking_snapshot import build_scan_view
    base = {'schema_version':1, 'read_only':True, 'freshness_verified':False,
            'media_actions_authorized':False, 'history_scope':'current_process',
            'history_persistent':False, 'per_title_details_available':False,
            'skipped_title_count':None, 'blocked_title_count':None}
    if not isinstance(capture, dict) or not isinstance(capture.get('run'), dict):
        return {**base, 'status':'unavailable', 'current':None, 'rows':None}
    run = capture['run']
    view = build_scan_view(run, capture.get('history'), title_details=False)
    if run.get('status') != 'advisory_only' or not view['history_available']:
        return {**base, 'status':'unavailable', 'current':None, 'rows':None}
    return {**base, 'status':'advisory_only', 'history_scope':view['history_scope'],
            'history_persistent':run.get('history_persistent') is True, 'history_partial':view['history_partial'],
            'current':{'state':view['current_state'], 'detail':view['current_detail']},
            'rows':view['rows']}




def selected_backup_status():
    """Inspect one operator-pinned packet; never find, create or adopt a backup."""
    import re
    from datetime import datetime, timezone
    base = {'schema_version':1, 'read_only':True, 'automatic_action':'none',
            'media_actions_authorized':False, 'restore_authorized':False,
            'restore_tested':False, 'current_state_comparison':'not_performed',
            'backup_scope':'explicitly_selected_packet', 'freshness_verified':False,
            'backup_kind':'logical_tracking_and_settings', 'captured_at':None,
            'age_seconds':None, 'verified_at':None, 'capture_time_status':'unknown'}
    directory = setting('INTEGRATION_API_BACKUP_DIRECTORY')
    identity = setting('INTEGRATION_API_BACKUP_IDENTITY')
    fingerprint = setting('INTEGRATION_API_BACKUP_FINGERPRINT')
    if not any((directory, identity, fingerprint)):
        return {**base, 'status':'not_configured', 'packet_verified':False}
    if (not directory or not re.fullmatch(r'[0-9]{1,20}:[0-9]{1,20}', identity)
            or not re.fullmatch(r'[0-9a-f]{64}', fingerprint)):
        return {**base, 'status':'selection_invalid', 'packet_verified':False}
    try:
        from app.json_backup import inspect_backup as inspect_update_backup
        report = inspect_update_backup(directory=directory, expected_identity=tuple(map(int,identity.split(':'))),
                                       expected_fingerprint=fingerprint, max_total_bytes=16 * 1024 * 1024)
        now = datetime.now(timezone.utc)
        captured = report['captured_at']
        age = (now - datetime.fromisoformat(captured)).total_seconds() if captured else None
        return {**base, 'status':'packet_verified', 'packet_verified':True,
                'captured_at':captured, 'age_seconds':int(age) if age is not None and age >= 0 else None,
                'capture_time_status':'unknown' if age is None else 'future' if age < 0 else 'recorded',
                'verified_at':now.isoformat(), 'payload_files_verified':2}
    except (ImportError, OSError, RuntimeError, ValueError, TypeError, KeyError, AttributeError):
        return {**base, 'status':'verification_failed', 'packet_verified':False}
