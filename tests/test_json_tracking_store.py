"""Atomic JSON storage for the isolated worker; production remains untouched."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from app.json_tracking_store import JsonTrackingStore
from app.sqlite_lock import StateLockBusy


def state():
    return {'first_seen': {'Movie':'2026-01-01T01:02:03', 'TV/Show':'2026-01-02T02:03:04'},
        'queued':{}, 'in_removal':{}, 'keep_seen':{}, 'arr_sync_pending':{},
        'unknown': {'retained':[1, 'private-extension']}}


@pytest.fixture
def store(tmp_path):
    path = tmp_path/'state.json'; path.write_text(json.dumps(state()))
    return JsonTrackingStore(path)


def test_explicit_atomic_checkpoint_preserves_clocks_extensions_and_private_mode(store):
    with store.session() as session:
        session.state['keep_seen']['Kept'] = '2026-01-03T03:04:05'
        expected = deepcopy(session.state)
        session.checkpoint()
        assert json.loads(store.path.read_bytes()) == expected
    with store.session() as fresh: assert fresh.state == expected
    assert store.path.stat().st_mode & 0o777 == 0o600


def test_exit_and_exception_never_save_uncheckpointed_changes(store):
    raw = store.path.read_bytes()
    with store.session() as session: session.state['first_seen'].clear()
    assert store.path.read_bytes() == raw
    with pytest.raises(RuntimeError):
        with store.session() as session:
            session.state.clear(); raise RuntimeError('synthetic')
    assert store.path.read_bytes() == raw
    with pytest.raises(RuntimeError): session.checkpoint()


@pytest.mark.parametrize('raw', [b'{}', b'{broken', b'{"first_seen":{},"first_seen":{}}',
    json.dumps({**state(), 'unknown':float('nan')}).encode(),
    json.dumps({**state(), 'queued':{'Bad':'2098-01-01'}}).encode()])
def test_invalid_state_never_resets_or_writes(store, raw):
    store.path.write_bytes(raw)
    with pytest.raises((RuntimeError, ValueError)):
        with store.session(): pytest.fail('Invalid state accepted')
    assert store.path.read_bytes() == raw


def test_missing_state_is_not_created(store):
    store.path.unlink()
    with pytest.raises(FileNotFoundError):
        with store.session(): pass
    assert not store.path.exists()


@pytest.mark.parametrize('kind', ['symlink', 'hardlink', 'directory'])
def test_unsafe_state_is_not_followed_or_modified(store, kind):
    raw = store.path.read_bytes(); target = store.path.with_name('retained.json')
    store.path.rename(target)
    if kind == 'symlink': store.path.symlink_to(target)
    elif kind == 'hardlink': os.link(target, store.path)
    else: store.path.mkdir()
    with pytest.raises((RuntimeError, OSError)):
        with store.session(): pass
    assert target.read_bytes() == raw


@pytest.mark.parametrize('identical', [False, True])
def test_external_replacement_is_not_overwritten(store, identical):
    with pytest.raises(RuntimeError):
        with store.session() as session:
            replacement = store.path.with_name('replacement.json')
            replacement.write_bytes(store.path.read_bytes() if identical else b'changed externally')
            replacement.replace(store.path)
            session.checkpoint()
    assert store.path.read_bytes() == (json.dumps(state()).encode() if identical else b'changed externally')


def test_other_process_is_blocked_for_entire_session(store):
    code = '''import sys
from app.json_tracking_store import JsonTrackingStore
from app.sqlite_lock import StateLockBusy
try:
 with JsonTrackingStore(sys.argv[1]).session(): raise SystemExit(9)
except StateLockBusy: raise SystemExit(0)
'''
    with store.session():
        result = subprocess.run([sys.executable,'-B','-c',code,str(store.path)], timeout=10)
        assert result.returncode == 0
    with store.session(): pass


def test_failed_replace_retains_original_and_releases_lock(store, monkeypatch):
    raw = store.path.read_bytes()
    with monkeypatch.context() as patch:
        patch.setattr(os, 'replace', lambda *a, **k: (_ for _ in ()).throw(OSError('synthetic')))
        with pytest.raises(OSError):
            with store.session() as session:
                session.state['first_seen'].clear(); session.checkpoint()
    assert store.path.read_bytes() == raw
    assert list(store.path.parent.glob('.json-worker-*.tmp')) == []
    with store.session(): pass


@pytest.mark.parametrize('phase', ['before_replace', 'after_replace'])
def test_actual_process_death_leaves_a_complete_old_or_new_snapshot(store, phase):
    before = store.path.read_bytes()
    code = '''import os, signal, sys
from app.json_tracking_store import JsonTrackingStore
phase, path = sys.argv[1:]
original_replace, original_fsync = os.replace, os.fsync
if phase == "before_replace":
 def stop(*a, **k): os.kill(os.getpid(), signal.SIGKILL)
 os.replace = stop
else:
 calls = 0
 def stop(fd):
  global calls
  calls += 1
  if calls == 2: os.kill(os.getpid(), signal.SIGKILL)
  return original_fsync(fd)
 os.fsync = stop
with JsonTrackingStore(path).session() as session:
 session.state["keep_seen"]["Committed"] = "2026-01-03T03:04:05"
 session.checkpoint()
'''
    result = subprocess.run([sys.executable,'-B','-c',code,phase,str(store.path)], timeout=10)
    assert result.returncode == -9
    with store.session() as session:
        expected = state()
        if phase == 'after_replace': expected['keep_seen']['Committed'] = '2026-01-03T03:04:05'
        assert session.state == expected
    if phase == 'before_replace': assert store.path.read_bytes() == before
