import json
import os

import pytest

from app import sqlite_host_controller as controller

BOOT='11111111-1111-4111-8111-111111111111'


@pytest.fixture
def root(tmp_path,monkeypatch):
    monkeypatch.setattr(controller,'_scope',lambda:(BOOT,'net:[1]','mnt:[2]'))
    monkeypatch.setattr(controller,'unique_mount_id',lambda path:2**32+7)
    return tmp_path.resolve()/'private-control'


def test_live_lock_and_retained_preparation_never_authorize_external_action(root):
    with controller.prepare_host_controller(root) as session:
        report=session.report()
        assert report['status']=='blocked' and all(report['scope_matches'].values())
        assert report['external_actions_authorized'] is False
        assert 'private_host_control_location_unverified' in report['blockers']
        with pytest.raises(RuntimeError,match='Live controller lock held'):
            controller.review_host_controller(root)
    before={p.name:p.read_bytes() for p in root.iterdir()}
    report=controller.review_host_controller(root)
    assert report['read_only'] is True and report['controller_adoption_authorized'] is False
    assert {p.name:p.read_bytes() for p in root.iterdir()}==before
    assert root.stat().st_mode & 0o777==0o700
    assert all(p.stat().st_mode & 0o777==0o600 for p in root.iterdir())
    with pytest.raises(RuntimeError,match='session unavailable'):session.report()
    with pytest.raises(FileExistsError):
        with controller.prepare_host_controller(root):pass
    assert {p.name:p.read_bytes() for p in root.iterdir()}==before


def test_controller_interruption_retains_request_without_replay(root):
    with pytest.raises(RuntimeError,match='interrupted'):
        with controller.prepare_host_controller(root):raise RuntimeError('interrupted')
    pending=(root/'maintenance-request.json').read_bytes()
    assert controller.review_host_controller(root)['phase']=='maintenance_requested'
    assert (root/'maintenance-request.json').read_bytes()==pending


@pytest.mark.parametrize('drift',['scope','mount','request','lock','permissions','fork_pid'])
def test_live_binding_loss_stays_failed_after_environment_recovers(root,monkeypatch,drift):
    with pytest.raises(RuntimeError,match='session unavailable'):
        with controller.prepare_host_controller(root) as session:
            if drift=='scope':
                monkeypatch.setattr(controller,'_scope',lambda:(BOOT,'net:[1]','mnt:[3]'))
            elif drift=='mount':monkeypatch.setattr(controller,'unique_mount_id',lambda path:99)
            elif drift=='request':(root/'maintenance-request.json').write_bytes(b'changed')
            elif drift=='lock':
                (root/'controller.lock').rename(root/'old-lock')
                (root/'controller.lock').touch(mode=0o600)
            elif drift=='permissions':root.chmod(0o755)
            else:
                original_pid=os.getpid()
                monkeypatch.setattr(controller.os,'getpid',lambda:original_pid+1)
            with pytest.raises(RuntimeError):session.check()
            monkeypatch.setattr(controller,'_scope',lambda:(BOOT,'net:[1]','mnt:[2]'))
            monkeypatch.setattr(controller,'unique_mount_id',lambda path:2**32+7)
            with pytest.raises(RuntimeError,match='session unavailable'):session.check()


@pytest.mark.parametrize('kind',['scope','mount','session'])
def test_review_reports_changed_scope_without_adopting(root,monkeypatch,kind):
    with controller.prepare_host_controller(root):pass
    if kind=='scope':monkeypatch.setattr(controller,'_scope',lambda:('22222222-2222-4222-8222-222222222222','net:[1]','mnt:[2]'))
    elif kind=='mount':monkeypatch.setattr(controller,'unique_mount_id',lambda path:99)
    else:monkeypatch.setattr(controller,'_SESSION','a'*64)
    result=controller.review_host_controller(root)
    assert any(b.startswith('scope_changed:') for b in result['blockers'])
    assert result['controller_adoption_authorized'] is False
    assert result['restoration_authorized'] is False


@pytest.mark.parametrize('change',[
    lambda r:r.update(schema_version=True),lambda r:r.update(production_authorized=True),
    lambda r:r.update(external_actions_authorized=True),lambda r:r.update(phase='released'),
    lambda r:r.update(extra='unknown'),lambda r:r.update(controller_pid=False),
])
def test_modified_request_never_authorizes_or_repairs(root,change):
    with controller.prepare_host_controller(root):pass
    path=root/'maintenance-request.json'
    request=json.loads(path.read_bytes());change(request)
    path.write_text(json.dumps(request))
    before=path.read_bytes()
    with pytest.raises(RuntimeError,match='Invalid retained controller request'):
        controller.review_host_controller(root)
    assert path.read_bytes()==before


def test_missing_lock_not_created_by_review(root):
    with controller.prepare_host_controller(root):pass
    (root/'controller.lock').unlink()
    with pytest.raises(FileNotFoundError):controller.review_host_controller(root)
    assert not (root/'controller.lock').exists()


def test_capability_failure_precedes_directory_creation(root,monkeypatch):
    def fail(path):raise RuntimeError('Unsupported mount capability')
    monkeypatch.setattr(controller,'unique_mount_id',fail)
    with pytest.raises(RuntimeError,match='Unsupported mount capability'):
        with controller.prepare_host_controller(root):pass
    assert not root.exists()


@pytest.mark.parametrize('fail_at',range(1,7))
def test_sync_failure_never_yields_live_session_and_retains_partial_state(root,monkeypatch,fail_at):
    actual=controller.os.fsync
    calls=0
    def fail(fd):
        nonlocal calls
        calls+=1
        if calls==fail_at:raise OSError('sync failed')
        actual(fd)
    monkeypatch.setattr(controller.os,'fsync',fail)
    with pytest.raises(OSError,match='sync failed'):
        with controller.prepare_host_controller(root):pytest.fail('No session')
    assert root.is_dir()
    with pytest.raises(FileExistsError):
        with controller.prepare_host_controller(root):pass
