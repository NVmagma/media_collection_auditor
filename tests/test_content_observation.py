from datetime import datetime
import os
from pathlib import Path

import pytest

import app.content_observation as module
from app.content_observation import ScheduledContentBlocked, observe_scheduled_content

NOW = datetime(2026, 10, 24)
OLD = datetime(2026, 1, 1)
NEW = datetime(2026, 10, 1)


def observe(root, **kwargs):
    return observe_scheduled_content(title_path=str(root), now=NOW, **kwargs)


def stamp(path, at):
    os.utime(path, (at.timestamp(), at.timestamp()))


def test_nested_files_and_directories_match_existing_newest_policy(tmp_path):
    season = tmp_path / 'Season 1'; season.mkdir()
    episode = season / 'episode.mkv'; episode.write_bytes(b'fixture')
    stamp(episode, NEW); stamp(season, OLD)
    assert observe(tmp_path) == NEW
    stamp(season, datetime(2026, 10, 2))
    assert observe(tmp_path) == datetime(2026, 10, 2)
    assert episode.read_bytes() == b'fixture'


def test_empty_title_has_no_descendant_timestamp(tmp_path):
    assert observe(tmp_path) is None


@pytest.mark.parametrize('target', ['file', 'directory'])
def test_symlink_content_is_never_followed(tmp_path, target):
    destination = tmp_path / 'real'
    destination.mkdir() if target == 'directory' else destination.write_text('keep')
    (tmp_path / 'link').symlink_to(destination)
    with pytest.raises(ScheduledContentBlocked, match='unsupported_content'):
        observe(tmp_path)


def test_nested_depth_budget(tmp_path):
    (tmp_path / 'Season').mkdir(); stamp(tmp_path / 'Season', OLD)
    with pytest.raises(ScheduledContentBlocked, match='depth_limit'):
        observe(tmp_path, maximum_depth=0)


def test_global_entry_budget_counts_nested_files(tmp_path):
    season = tmp_path / 'Season'; season.mkdir()
    (season / 'episode').write_text('keep')
    stamp(season, OLD); stamp(season / 'episode', OLD)
    with pytest.raises(ScheduledContentBlocked, match='entry_limit'):
        observe(tmp_path, maximum_entries=1)


def test_deadline_stops_observation(tmp_path):
    ticks = iter(range(100))
    with pytest.raises(ScheduledContentBlocked, match='deadline'):
        observe(tmp_path, maximum_seconds=1, timer=lambda: next(ticks))


def test_future_timestamp_blocks_instead_of_returning_stale_clock(tmp_path):
    (tmp_path / 'future').write_text('keep')
    stamp(tmp_path / 'future', datetime(2030, 1, 1))
    with pytest.raises(ScheduledContentBlocked, match='future_content'):
        observe(tmp_path)


def test_unreadable_subdirectory_has_no_partial_result(tmp_path, monkeypatch):
    season = tmp_path / 'Season'; season.mkdir(); stamp(season, OLD)
    real = module.os.open
    def denied(path, *args, **kwargs):
        if path == 'Season': raise PermissionError('private diagnostic')
        return real(path, *args, **kwargs)
    monkeypatch.setattr(module.os, 'open', denied)
    with pytest.raises(ScheduledContentBlocked, match='content_unavailable') as error:
        observe(tmp_path)
    assert 'private diagnostic' not in str(error.value)


def test_file_changes_between_inventory_passes_block(tmp_path, monkeypatch):
    episode = tmp_path / 'episode'; episode.write_text('keep'); stamp(episode, OLD)
    real = module.os.scandir; calls = []
    def scan(fd):
        calls.append(fd)
        if len(calls) == 2:
            episode.write_text('changed')
            stamp(episode, NEW)
        return real(fd)
    monkeypatch.setattr(module.os, 'scandir', scan)
    with pytest.raises(ScheduledContentBlocked, match='content_changed'):
        observe(tmp_path)


def test_symlink_title_path_rejected(tmp_path):
    root = tmp_path / 'title'; root.mkdir()
    alias = tmp_path / 'alias'; alias.symlink_to(root, target_is_directory=True)
    with pytest.raises(ScheduledContentBlocked):
        observe(alias)
