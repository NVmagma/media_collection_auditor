#!/usr/bin/env python3
"""Fixed loopback client for a NEW isolated Jellyfin fixture, never production."""
import argparse
from datetime import datetime
import errno
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import signal
import sys
import time
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.sqlite_jellyfin_collection import collect_title_observation

MEDIA = Path('/media')
CONTROL = Path('/control')
MARKER = b'DISPOSABLE JELLYFIN READONLY FIXTURE\n'
FOLDER = 'Fixture Movie (2024)'
SERVER_NAME = 'Auditor isolated readonly fixture'


class FixtureHTTPError(RuntimeError):
    def __init__(self, status, route):
        self.status = status
        self.route = re.sub(r'/[a-fA-F0-9]{32}', '/<id>', route.split('?')[0])
        super().__init__('fixture_http_response_rejected')


def media_manifest():
    if (MEDIA / '.fixture-only').read_bytes() != MARKER:
        raise RuntimeError('fixture_marker_invalid')
    observed = {}
    for path in sorted(MEDIA.rglob('*')):
        if path.is_symlink() or not (path.is_dir() or path.is_file()):
            raise RuntimeError('fixture_media_unsafe')
        if path.is_file():
            observed[str(path.relative_to(MEDIA))] = hashlib.sha256(path.read_bytes()).hexdigest()
    if set(observed) != {'.fixture-only', 'Movies/' + FOLDER + '/' + FOLDER + '.mkv',
                         'Movies/' + FOLDER + '/movie.nfo'}:
        raise RuntimeError('fixture_media_layout_invalid')
    return observed


def request(method, path, body=None, token=None):
    # No URL argument, proxy environment, redirects or automatic write retries.
    if not path.startswith('/') or path.startswith('//'):
        raise RuntimeError('fixture_request_invalid')
    connection = http.client.HTTPConnection('127.0.0.1', 8096, timeout=4)
    headers = {'Authorization': 'MediaBrowser Client="AuditorFixture", Device="Disposable", DeviceId="readonly-fixture", Version="1"'}
    if token:
        headers['X-Emby-Token'] = token
    encoded = None if body is None else json.dumps(body).encode()
    if encoded is not None:
        headers['Content-Type'] = 'application/json'
    try:
        connection.request(method, path, body=encoded, headers=headers)
        response = connection.getresponse()
        raw = response.read(4 * 1024 * 1024 + 1)
        if response.status not in (200, 204) or len(raw) > 4 * 1024 * 1024:
            raise FixtureHTTPError(response.status, path)
        return json.loads(raw) if raw else None
    finally:
        connection.close()


def wait_public():
    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        try:
            value = request('GET', '/System/Info/Public')
            if isinstance(value, dict) and type(value.get('StartupWizardCompleted')) is bool:
                return value
        except (OSError, RuntimeError, ValueError, http.client.HTTPException):
            pass  # Bounded GET readiness polling only; POSTs are never retried.
        time.sleep(1)
    raise RuntimeError('fixture_startup_timeout')


def credential():
    data = json.loads((CONTROL / 'credential.json').read_text())
    if set(data) != {'username', 'password'} or data['username'] != 'auditor-fixture':
        raise RuntimeError('fixture_credential_invalid')
    return data


def authenticate(data):
    auth = request('POST', '/Users/AuthenticateByName', {'Username': data['username'], 'Pw': data['password']})
    uid, token = auth['User']['Id'], auth['AccessToken']
    if not isinstance(uid, str) or not re.fullmatch(r'[0-9a-fA-F]{32}', uid) or not isinstance(token, str) or not token:
        raise RuntimeError('fixture_authentication_invalid')
    return uid, token


def prepare():
    snapshot = media_manifest()
    data = {'username': 'auditor-fixture', 'password': secrets.token_urlsafe(32)}
    for name, value in [('credential.json', data), ('manifest.json', snapshot)]:
        fd = os.open(CONTROL / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as handle:
            json.dump(value, handle)
    return {'status': 'fixture_inputs_prepared'}


def setup():
    info = wait_public()
    if info['StartupWizardCompleted'] is not False:
        raise RuntimeError('fixture_must_be_fresh')
    data = credential()
    request('GET', '/Startup/User')
    request('POST', '/Startup/User', {'Name': data['username'], 'Password': data['password']})
    request('POST', '/Startup/Configuration', {'ServerName': SERVER_NAME, 'UICulture': 'en-US',
                                             'MetadataCountryCode': 'US', 'PreferredMetadataLanguage': 'en'})
    request('POST', '/Startup/Complete')
    uid, token = authenticate(data)
    request('POST', '/Library/VirtualFolders?' + urlencode({'name': 'Fixture', 'collectionType': 'movies',
             'paths': '/media/Movies', 'refreshLibrary': 'true'}),
            {'LibraryOptions': {'EnableRealtimeMonitor': False, 'SaveLocalMetadata': False}}, token)
    deadline = time.monotonic() + 60
    item = None
    while time.monotonic() < deadline:
        page = request('GET', '/Users/' + uid + '/Items?' + urlencode({
            'Recursive': 'true', 'IncludeItemTypes': 'Movie', 'Fields': 'Path,Tags', 'Limit': 10}), token=token)
        if page.get('TotalRecordCount') == 1 and len(page.get('Items', [])) == 1:
            candidate = page['Items'][0]
            if candidate.get('Type') == 'Movie' and 'keep-forever' in candidate.get('Tags', []):
                item = candidate
                break
        time.sleep(1)
    if item is None or not re.fullmatch(r'[0-9a-fA-F]{32}', item.get('Id', '')):
        raise RuntimeError('fixture_library_scan_unverified')
    request('POST', '/Users/' + uid + '/FavoriteItems/' + item['Id'], token=token)
    with (CONTROL / 'server.json').open('x') as handle:
        json.dump({'id': info['Id']}, handle)
    return check()


def check():
    if media_manifest() != json.loads((CONTROL / 'manifest.json').read_text()):
        raise RuntimeError('fixture_media_changed')
    # One explicit fixed write probe per check; no retry or repair on failure.
    try:
        fd = os.open(MEDIA / '.must-not-create', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError as exc:
        if exc.errno != errno.EROFS:
            raise RuntimeError('fixture_denial_not_erofs') from None
    else:
        os.close(fd)
        raise RuntimeError('fixture_media_write_succeeded')
    info = wait_public()
    recorded = json.loads((CONTROL / 'server.json').read_text())
    if info['StartupWizardCompleted'] is not True or info.get('ServerName') != SERVER_NAME or info.get('Id') != recorded['id']:
        raise RuntimeError('fixture_server_identity_changed')
    _, token = authenticate(credential())
    observation = collect_title_observation(
        fetch=lambda path, params: request('GET', path + ('?' + urlencode(params) if params else ''), token=token),
        jellyfin_type='Movie', folder=FOLDER, media_key=FOLDER, now=datetime.now())
    if observation['status'] != 'shape_valid_untrusted' or observation['blockers']:
        raise RuntimeError('fixture_protection_read_unverified')
    signals = observation['signals']
    if not (signals['protected'] and signals['keep_all'] and signals['favorite']):
        raise RuntimeError('fixture_protections_missing')
    if media_manifest() != json.loads((CONTROL / 'manifest.json').read_text()):
        raise RuntimeError('fixture_media_changed')
    return {'status': 'real_jellyfin_readonly_fixture_verified', 'media_write_denial': 'EROFS',
            'protection_read_available': True, 'protected': True, 'favorite': True,
            'media_bytes_unchanged': True,
            'jellyfin_version': info.get('Version') if isinstance(info.get('Version'), str) and re.fullmatch(r'[0-9A-Za-z.+-]{1,64}', info['Version']) else None}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--phase', choices=('prepare', 'setup', 'check'), required=True)
    args = parser.parse_args(argv)
    if hasattr(signal, 'SIGALRM'):
        signal.signal(signal.SIGALRM, lambda *unused: os._exit(124))
        signal.alarm(165)
    try:
        report = {'prepare': prepare, 'setup': setup, 'check': check}[args.phase]()
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, http.client.HTTPException) as exc:
        if hasattr(signal, 'SIGALRM'):
            signal.alarm(0)
        report = {'status': 'blocked', 'phase': args.phase, 'fixture_only': True,
                  'production_authorized': False, 'production_activation': 'disabled',
                  'writer_exclusion_verified': False,
                  'failure_category': str(exc) if re.fullmatch(r'fixture_[a-z_]+', str(exc)) else type(exc).__name__}
        if isinstance(exc, FixtureHTTPError):
            report.update(http_status=exc.status, route=exc.route)
        print(json.dumps(report))
        return 2
    if hasattr(signal, 'SIGALRM'):
        signal.alarm(0)
    report.update(fixture_only=True, production_authorized=False,
                  production_activation='disabled', writer_exclusion_verified=False)
    print(json.dumps(report))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
