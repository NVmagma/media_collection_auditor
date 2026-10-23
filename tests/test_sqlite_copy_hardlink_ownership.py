"""External hard-link aliases cannot inherit a title-folder ownership assumption."""
import os

import pytest

from app.sqlite_copy_live_verification import _metadata_snapshot, refresh_hashed_copy
from app.sqlite_disposable_copy_stage import FLAGS, _manifest, stage_disposable_verified_copy
from app.sqlite_collected_isolated_runner import run_collected_isolated_copy_completion
from app.state_store import GuardedSQLiteStateStore
from tests.test_sqlite_collected_isolated_runner import lab, item, transport, NOW, FOLDER, LIMITS


@pytest.mark.parametrize('nested', [False, True])
def test_existing_external_alias_blocks_before_any_intent_or_media_action(tmp_path, nested):
    root, database = lab(tmp_path)
    tree = root/'transient'/FOLDER
    path = tree/'payload'
    if nested:
        (tree/'Season 01').mkdir()
        path = tree/'Season 01'/'episode'
        path.write_bytes(b'episode')
    alias = tmp_path/'outside-download-alias'
    os.link(path, alias)
    before = database.read_bytes()
    content = path.read_bytes()
    fetch, _ = transport([[item()]])
    with pytest.raises(RuntimeError, match='unverified hard-link aliases'):
        run_collected_isolated_copy_completion(root=root, database=database,
            operation_id='hardlink-copy', media_key=FOLDER, title_folder=FOLDER,
            jellyfin_type='Movie', thresholds=LIMITS, fetch=fetch, clock=lambda: NOW,
            arr_sync_request={'service':'radarr','title_id':42,'root':'/fixture/holding','monitored':False})
    assert database.read_bytes() == before
    state = GuardedSQLiteStateStore(database).load_with_revision()[0]
    assert state['first_seen'][FOLDER] == '2024-01-01T00:00:00'
    assert not state['queued'] and not state['arr_sync_pending']
    assert 'sqlite_pending_operations' not in state
    assert not (root/'.sqlite_copy_staging').exists()
    assert not (root/'holding'/FOLDER).exists()
    assert path.read_bytes() == alias.read_bytes() == content
    assert path.stat().st_ino == alias.stat().st_ino


@pytest.mark.parametrize('target', ['source','copy'])
def test_alias_added_during_fresh_protection_read_blocks_hash_acceptance(tmp_path, target):
    source = tmp_path/'source'
    copied = tmp_path/'copy'
    for tree in (source, copied):
        tree.mkdir()
        (tree/'payload').write_bytes(b'fixture')
    fds = [os.open(tree, FLAGS) for tree in (source,copied)]
    try:
        trees = tuple((fd, _manifest(fd)[1]) for fd in fds)
        def refresh():
            os.link((source if target=='source' else copied)/'payload', tmp_path/'outside-alias')
        with pytest.raises(RuntimeError, match='unverified hard-link aliases'):
            refresh_hashed_copy(trees=trees, refresh=refresh, check_window=lambda: None)
        assert (source/'payload').read_bytes() == (copied/'payload').read_bytes() == b'fixture'
        assert (tmp_path/'outside-alias').read_bytes() == b'fixture'
    finally:
        for fd in fds:
            os.close(fd)


def test_copy_only_diagnostic_preserves_alias_and_copies_independent_bytes(tmp_path):
    root, database = lab(tmp_path)
    source = root/'transient'/FOLDER/'payload'
    alias = tmp_path/'outside-download-alias'
    os.link(source, alias)
    before = database.read_bytes()
    report = stage_disposable_verified_copy(root=root, title_folder=FOLDER, operation_id='copy-only')
    copied = root/'.sqlite_copy_staging'/'copy-only'/'payload'
    assert report['tracking_committed'] is False
    assert report['promotion_authorized'] is False
    assert copied.read_bytes() == source.read_bytes() == alias.read_bytes()
    assert copied.stat().st_ino != source.stat().st_ino
    assert source.stat().st_nlink == 2
    assert database.read_bytes() == before


@pytest.mark.parametrize('boundary', ['opened','after','bound'])
def test_link_count_drift_is_checked_even_if_timestamp_identity_is_unchanged(tmp_path, monkeypatch, boundary):
    # Emulate a filesystem with coarser identity timestamps. The explicit link
    # count check must not rely on a changed ctime to detect alias creation.
    import app.sqlite_copy_live_verification as module
    (tmp_path/'payload').write_bytes(b'fixture')
    fd = os.open(tmp_path, FLAGS)
    real_fstat, real_stat = os.fstat, os.stat
    calls = 0
    def altered(info):
        values = list(info)
        values[3] = 2  # stat_result.st_nlink
        return os.stat_result(values)
    def fstat(descriptor):
        nonlocal calls
        info = real_fstat(descriptor)
        if info.st_ino == real_stat(tmp_path/'payload').st_ino:
            calls += 1
            if (boundary=='opened' and calls==1) or (boundary=='after' and calls==2):
                return altered(info)
        return info
    def stat(path, *args, **kwargs):
        info = real_stat(path,*args,**kwargs)
        if boundary=='bound' and path=='payload':
            stat.seen += 1
            if stat.seen==2:
                return altered(info)
        return info
    stat.seen=0
    monkeypatch.setattr(module.os,'fstat',fstat)
    monkeypatch.setattr(module.os,'stat',stat)
    try:
        with pytest.raises(RuntimeError, match='unverified hard-link aliases'):
            _metadata_snapshot(fd)
    finally:
        os.close(fd)


@pytest.mark.parametrize('target', ['source','staging'])
def test_alias_after_durable_intent_preserves_pending_state_without_publication(tmp_path, monkeypatch, target):
    import app.sqlite_disposable_copy_stage as stage
    root, database = lab(tmp_path)
    alias = tmp_path/'outside-writer-alias'
    original = stage._copy_tree
    def copy(source_fd, destination_fd):
        original(source_fd, destination_fd)
        os.link('payload', alias, src_dir_fd=source_fd if target=='source' else destination_fd)
    monkeypatch.setattr(stage,'_copy_tree',copy)
    fetch, _ = transport([[item()]])
    with pytest.raises(RuntimeError, match='unverified hard-link aliases|verification mismatch'):
        run_collected_isolated_copy_completion(root=root, database=database,
            operation_id='late-hardlink-copy', media_key=FOLDER, title_folder=FOLDER,
            jellyfin_type='Movie', thresholds=LIMITS, fetch=fetch, clock=lambda: NOW)
    state = GuardedSQLiteStateStore(database).load_with_revision()[0]
    assert state['first_seen'][FOLDER] == '2024-01-01T00:00:00'
    assert not state['queued'] and not state['arr_sync_pending']
    pending = state['sqlite_pending_operations']
    assert pending['id'] == 'late-hardlink-copy'
    assert 'publication' not in pending['details']
    assert 'retirement' not in pending['details']
    assert not (root/'holding'/FOLDER).exists()
    assert not (root/'.sqlite_retained_sources').exists()
    assert (root/'transient'/FOLDER/'payload').read_text() == alias.read_text() == 'fixture'
