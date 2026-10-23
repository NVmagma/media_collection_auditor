"""Protocol tests use inert HTTP responses, not a running Jellyfin or host media."""
import errno
import json
from pathlib import Path

import pytest
from scripts import sqlite_jellyfin_readonly_fixture as module

UID = 'a' * 32
ITEM = 'b' * 32
SERVER = 'c' * 32


@pytest.fixture
def fixture_files(tmp_path, monkeypatch):
    media = tmp_path / 'media'
    control = tmp_path / 'control'
    folder = media / 'Movies' / module.FOLDER
    folder.mkdir(parents=True)
    control.mkdir()
    (media / '.fixture-only').write_bytes(module.MARKER)
    (folder / (module.FOLDER + '.mkv')).write_bytes(b'synthetic movie')
    (folder / 'movie.nfo').write_bytes(b'synthetic nfo')
    monkeypatch.setattr(module, 'MEDIA', media)
    monkeypatch.setattr(module, 'CONTROL', control)
    module.prepare()
    (control / 'server.json').write_text(json.dumps({'id': SERVER}))
    return media, control


def test_prepare_is_exclusive_and_private(fixture_files):
    _, control = fixture_files
    assert (control / 'credential.json').stat().st_mode & 0o777 == 0o600
    before = (control / 'credential.json').read_bytes()
    with pytest.raises(FileExistsError):
        module.prepare()
    assert (control / 'credential.json').read_bytes() == before


def transport(method, path, body=None, token=None):
    if path == '/Users/AuthenticateByName':
        return {'User': {'Id': UID}, 'AccessToken': 'fixture-token-must-not-print'}
    assert method == 'GET'
    if path == '/Users':
        return [{'Id': UID}]
    if path.startswith('/Users/' + UID + '/Items?'):
        return {'TotalRecordCount': 1, 'Items': [{
            'Id': ITEM, 'Type': 'Movie', 'Path': '/media/Movies/' + module.FOLDER + '/film.mkv',
            'Tags': ['keep-forever'], 'UserData': {'IsFavorite': True, 'Played': False, 'PlayCount': 0}}]}
    pytest.fail('Unexpected fixture route')


def readonly(monkeypatch):
    original = module.os.open
    def open_ro(path, *args, **kwargs):
        if Path(path).name == '.must-not-create':
            raise OSError(errno.EROFS, 'readonly')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(module.os, 'open', open_ro)
    monkeypatch.setattr(module, 'wait_public', lambda: {'StartupWizardCompleted': True,
        'ServerName': module.SERVER_NAME, 'Id': SERVER})
    monkeypatch.setattr(module, 'request', transport)


def test_real_collector_contract_under_declared_ro_view(fixture_files, monkeypatch):
    readonly(monkeypatch)
    report = module.check()
    assert report['media_write_denial'] == 'EROFS'
    assert report['protected'] is True and report['favorite'] is True
    assert 'fixture-token' not in json.dumps(report)


@pytest.mark.parametrize('problem', ['missing_protection', 'bad_denial', 'writable', 'bytes_changed', 'server_changed'])
def test_failed_checks_never_become_acceptance(fixture_files, monkeypatch, problem):
    media, _ = fixture_files
    readonly(monkeypatch)
    if problem == 'missing_protection':
        def missing(*args, **kwargs):
            result = transport(*args, **kwargs)
            if isinstance(result, dict) and 'Items' in result:
                result['Items'][0]['Tags'] = []
            return result
        monkeypatch.setattr(module, 'request', missing)
    elif problem == 'bad_denial':
        def denied(*args, **kwargs): raise OSError(errno.EACCES, 'not readonly proof')
        monkeypatch.setattr(module.os, 'open', denied)
    elif problem == 'writable':
        monkeypatch.undo()
        monkeypatch.setattr(module, 'MEDIA', media)
        monkeypatch.setattr(module, 'CONTROL', fixture_files[1])
    elif problem == 'bytes_changed':
        (media / 'Movies' / module.FOLDER / 'movie.nfo').write_bytes(b'changed')
    else:
        monkeypatch.setattr(module, 'wait_public', lambda: {'StartupWizardCompleted': True,
            'ServerName': module.SERVER_NAME, 'Id': 'changed'})
    with pytest.raises(RuntimeError):
        module.check()


def test_existing_server_is_rejected_before_any_post(fixture_files, monkeypatch):
    monkeypatch.setattr(module, 'wait_public', lambda: {'StartupWizardCompleted': True})
    monkeypatch.setattr(module, 'request', lambda *a, **k: pytest.fail('No writes to initialized server'))
    with pytest.raises(RuntimeError, match='must_be_fresh'):
        module.setup()


def test_http_redirect_not_followed_and_no_write_retry(monkeypatch):
    calls = []
    class Response:
        status = 302
        def read(self, size): return b''
    class Connection:
        def __init__(self, host, port, timeout): assert host == '127.0.0.1' and port == 8096
        def request(self, *args, **kwargs): calls.append(args)
        def getresponse(self): return Response()
        def close(self): pass
    monkeypatch.setattr(module.http.client, 'HTTPConnection', Connection)
    with pytest.raises(module.FixtureHTTPError):
        module.request('POST', '/Startup/User', {'Password': 'private'})
    assert len(calls) == 1


def test_setup_sequence_only_initializes_fresh_fixture_once(fixture_files, monkeypatch):
    _, control = fixture_files
    (control / 'server.json').unlink()
    monkeypatch.setattr(module, 'wait_public', lambda: {'StartupWizardCompleted': False, 'Id': SERVER})
    calls = []
    def setup_transport(method, path, body=None, token=None):
        calls.append((method, path))
        if path == '/Users/AuthenticateByName' or (method == 'GET' and path.startswith('/Users/')):
            return transport(method, path, body, token)
        return None
    monkeypatch.setattr(module, 'request', setup_transport)
    monkeypatch.setattr(module, 'check', lambda: {'status': 'checked'})
    assert module.setup() == {'status': 'checked'}
    assert [path for method, path in calls if method == 'POST'][:3] == [
        '/Startup/User', '/Startup/Configuration', '/Startup/Complete']
    assert len([path for method, path in calls if method == 'POST']) == 6
    assert json.loads((control / 'server.json').read_text()) == {'id': SERVER}
