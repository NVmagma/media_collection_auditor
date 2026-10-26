from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from app.sqlite_run_schedule import DailyRunSchedule
from app.sqlite_scheduled_slot import claim_disposable_scheduled_slot
from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_state import SECTIONS

SLOT = datetime(2024, 2, 1, 2, tzinfo=timezone.utc)


def root(tmp_path):
    path = tmp_path / 'lab'; path.mkdir()
    (path / '.sqlite_disposable_rehearsal').write_text('DISPOSABLE ONLY\n')
    write_offline_snapshot({name: {} for name in SECTIONS}, path / 'state.db')
    return path


def claim(path, **kwargs):
    values = dict(root=path, schedule=DailyRunSchedule('02:00', 'UTC'), scheduled_at=SLOT, now=SLOT)
    values.update(kwargs)
    return claim_disposable_scheduled_slot(**values)


def test_slot_is_retained_and_duplicate_attempt_never_enters(tmp_path):
    path = root(tmp_path)
    with claim(path) as verify: verify()
    records = list((path / '.sqlite_scheduled_slots').iterdir())
    assert len(records) == 1
    before = records[0].read_bytes()
    assert json.loads(before)['automatic_replay'] is False
    with pytest.raises(FileExistsError):
        with claim(path): pytest.fail('Duplicate slot entered')
    assert records[0].read_bytes() == before


def test_exception_retains_claim_and_next_day_is_distinct(tmp_path):
    path = root(tmp_path)
    with pytest.raises(RuntimeError, match='injected'):
        with claim(path): raise RuntimeError('injected scan failure')
    with pytest.raises(FileExistsError):
        with claim(path): pytest.fail('Failed slot replayed')
    next_day = datetime(2024, 2, 2, 2, tzinfo=timezone.utc)
    with claim(path, scheduled_at=next_day, now=next_day): pass
    assert len(list((path / '.sqlite_scheduled_slots').iterdir())) == 2


@pytest.mark.parametrize('now', [datetime(2024, 2, 1, 1, tzinfo=timezone.utc),
                               datetime(2024, 2, 1, 2, 1, tzinfo=timezone.utc)])
def test_early_or_missed_slot_makes_no_claim(tmp_path, now):
    path = root(tmp_path)
    with pytest.raises(RuntimeError, match='not due or missed'):
        with claim(path, now=now): pytest.fail('Catch-up attempted')
    assert not (path / '.sqlite_scheduled_slots').exists()


def test_wrong_scheduled_time_makes_no_claim(tmp_path):
    path = root(tmp_path); wrong = datetime(2024, 2, 1, 3, tzinfo=timezone.utc)
    with pytest.raises(ValueError):
        with claim(path, scheduled_at=wrong, now=wrong): pytest.fail('Wrong time entered')


def test_schedule_change_same_zone_date_cannot_run_twice(tmp_path):
    path = root(tmp_path)
    with claim(path): pass
    other = datetime(2024, 2, 1, 3, tzinfo=timezone.utc)
    with pytest.raises(FileExistsError):
        with claim(path, schedule=DailyRunSchedule('03:00', 'UTC'), scheduled_at=other, now=other):
            pytest.fail('Same local date attempted twice')


def test_claim_directory_symlink_is_not_followed(tmp_path):
    path = root(tmp_path); target = tmp_path / 'target'; target.mkdir()
    (path / '.sqlite_scheduled_slots').symlink_to(target)
    with pytest.raises(OSError):
        with claim(path): pytest.fail('Symlink followed')
    assert list(target.iterdir()) == []


def test_failed_claim_flush_never_yields_and_cannot_replay_partial_record(tmp_path, monkeypatch):
    import os
    import stat
    path = root(tmp_path); original = os.fsync
    def fail_record(fd):
        if stat.S_ISREG(os.fstat(fd).st_mode):
            raise OSError('injected slot record flush failure')
        return original(fd)
    with monkeypatch.context() as local:
        local.setattr(os, 'fsync', fail_record)
        with pytest.raises(OSError):
            with claim(path): pytest.fail('Unflushed claim yielded')
    records = list((path / '.sqlite_scheduled_slots').iterdir())
    assert len(records) == 1
    with pytest.raises(FileExistsError):
        with claim(path): pytest.fail('Partial claim replayed')
