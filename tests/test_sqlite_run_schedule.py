from datetime import datetime, timezone

import pytest

from app.sqlite_run_schedule import DailyRunSchedule


def utc(value):
    return datetime.fromisoformat(value).replace(tzinfo=timezone.utc)


def test_two_am_local_time_is_explicit_and_returned_as_utc():
    schedule = DailyRunSchedule('02:00', 'America/Los_Angeles')
    assert schedule.next_start(utc('2026-10-24T08:00')) == utc('2026-10-24T09:00')


def test_restart_after_missed_slot_waits_for_next_day():
    schedule = DailyRunSchedule('02:00', 'America/Los_Angeles')
    assert schedule.next_start(utc('2026-10-24T10:00')) == utc('2026-10-25T09:00')


def test_exact_slot_is_not_replayed():
    assert DailyRunSchedule('02:00', 'UTC').next_start(utc('2026-10-24T02:00')) == utc('2026-10-25T02:00')


def test_nonexistent_spring_time_is_skipped():
    schedule = DailyRunSchedule('02:00', 'America/Los_Angeles')
    assert schedule.next_start(utc('2026-03-08T08:00')) == utc('2026-03-09T09:00')


def test_fall_ambiguous_time_uses_first_occurrence():
    schedule = DailyRunSchedule('01:30', 'America/Los_Angeles')
    assert schedule.next_start(utc('2026-11-01T07:00')) == utc('2026-11-01T08:30')
    assert schedule.next_start(utc('2026-11-01T08:45')) == utc('2026-11-02T09:30')


def test_non_hour_timezone_offset():
    assert DailyRunSchedule('02:00', 'Asia/Kathmandu').next_start(utc('2026-10-24T00:00')) == utc('2026-10-24T20:15')


@pytest.mark.parametrize('value', ['2:00', '24:00', '02:60', '02:00:00', ' 02:00', '02:00\n', '', None, True])
def test_invalid_clock_fails_closed(value):
    with pytest.raises(ValueError):
        DailyRunSchedule(value, 'UTC')


@pytest.mark.parametrize('value', ['', 'Unknown/Nowhere', '../UTC', '/etc/localtime', None])
def test_unavailable_or_implicit_zone_rejected(value):
    with pytest.raises(ValueError):
        DailyRunSchedule('02:00', value)


def test_naive_current_time_rejected():
    with pytest.raises(ValueError):
        DailyRunSchedule('02:00', 'UTC').next_start(datetime(2026, 10, 24))
