import hashlib
import json
from pathlib import Path
import os
import pytest
from scripts import sqlite_release_preflight as module


def inputs(tmp_path):
    state = {key: {} for key in module.SECTIONS}
    state['first_seen']['private-title-do-not-print'] = '2024-01-01'
    state['extension'] = {'token': 'never-print-this-secret'}
    source = tmp_path/'state.json'; source.write_text(json.dumps(state))
    config = tmp_path/'config.json'; config.write_text('{}')
    media = tmp_path/'media'; media.mkdir()
    for suffix in ('', '_hold', '_keep', '_removal'): (media/('Movies'+suffix)).mkdir()
    return {'STATE_FILE': str(source), 'WEB_CONFIG_FILE': str(config), 'MEDIA_PATH': str(media),
            'SQLITE_STATE_FILE': str(tmp_path/'control'/'state.db')}, source, config


def test_read_only_hash_counts_and_saved_precedence_without_private_data(tmp_path):
    env, source, config = inputs(tmp_path)
    env.update(DRY_RUN='false', INTEGRATION_API_TOKEN='never-print-this-secret',
               JELLYFIN_HOST_URL='http://user:never-print-this-secret@private-host')
    config.write_text(json.dumps({'DRY_RUN': True, 'SQLITE_DAILY_RUN_TIME': '02:00',
        'SQLITE_DAILY_RUN_TIMEZONE': 'America/Los_Angeles', 'JELLYFIN_API_TOKEN': 'never-print-this-secret'}))
    before = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    paths = set(tmp_path.rglob('*'))
    report = module.report(env)
    assert report['prospective_effective_settings']['DRY_RUN'] == 'true'
    assert report['prospective_effective_settings']['SQLITE_DAILY_RUN_TIME'] == '02:00'
    assert report['source_json']['counts']['first_seen'] == 1
    assert report['source_json']['sha256'] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert report['writer_quiescence_verified'] is False and report['source_snapshot_validated'] is False
    assert report['sqlite_control_directory']['status'] == 'unavailable_or_aliased'
    encoded = json.dumps(report)
    for secret in ('never-print-this-secret', 'private-title-do-not-print', 'private-host'):
        assert secret not in encoded
    assert set(tmp_path.rglob('*')) == paths
    assert all(path.read_bytes() == raw for path, raw in before.items())


@pytest.mark.parametrize('payload', ['{}', '{"first_seen":{},"first_seen":{}}', 'not-json'])
def test_invalid_source_is_unavailable_not_healthy_empty(tmp_path, payload):
    env, source, _ = inputs(tmp_path); source.write_text(payload)
    report = module.report(env)
    assert report['source_json']['status'] == 'unavailable_or_invalid'
    assert 'counts' not in report['source_json'] and 'sha256' not in report['source_json']


@pytest.mark.parametrize('alias', ['symlink', 'hardlink', 'fifo'])
def test_unsafe_source_is_refused_without_following_or_blocking(tmp_path, alias):
    env, source, _ = inputs(tmp_path)
    if alias == 'symlink':
        target = tmp_path/'target.json'; source.rename(target); source.symlink_to(target)
    elif alias == 'hardlink': os.link(source, tmp_path/'other-link.json')
    else:
        source.unlink(); os.mkfifo(source)
    assert module.report(env)['source_json']['status'] == 'unavailable_or_invalid'


def test_invalid_setting_text_is_redacted(tmp_path):
    env, _, config = inputs(tmp_path)
    config.write_text(json.dumps({'DRY_RUN': 'never-print-this-secret',
        'MAX_ACTIONS_PER_RUN': 'never-print-this-secret', 'SQLITE_DAILY_RUN_TIME': 'never-print-this-secret',
        'SQLITE_DAILY_RUN_TIMEZONE': 'never-print-this-secret'}))
    report = module.report(env)
    assert 'never-print-this-secret' not in json.dumps(report)
    assert report['prospective_effective_settings']['DRY_RUN'] == 'invalid'


def test_changed_source_cannot_supply_snapshot_hash(tmp_path, monkeypatch):
    env, source, _ = inputs(tmp_path)
    config = Path(env['WEB_CONFIG_FILE']); config.unlink()
    read = module.os.read; changed = []
    def concurrent(fd, count):
        data = read(fd, count)
        if data and not changed:
            changed.append(True); source.write_text('{}')
        return data
    monkeypatch.setattr(module.os, 'read', concurrent)
    report = module.report(env)
    assert report['source_json']['status'] == 'unavailable_or_invalid'
    assert 'sha256' not in report['source_json']


def test_alias_media_root_is_not_adopted(tmp_path):
    env, _, _ = inputs(tmp_path)
    original = Path(env['MEDIA_PATH']); alias = tmp_path/'alias'; alias.symlink_to(original, target_is_directory=True)
    env['MEDIA_PATH'] = str(alias)
    report = module.report(env)
    assert all(row['status'] == 'unavailable_or_aliased' for row in report['libraries']['Movies'].values())
