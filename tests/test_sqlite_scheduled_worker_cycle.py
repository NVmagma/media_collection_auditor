from datetime import datetime, timedelta, timezone
from unittest.mock import Mock

import pytest

from app.sqlite_scheduled_worker_cycle import ScheduledWorkerCycle

UTC = timezone.utc
START = datetime(2026, 10, 24, 1, tzinfo=UTC)


def step(cycle, now, callback, **kwargs):
    return cycle.step(now=now, run_due=callback, local_time=kwargs.get('local_time', '02:00'),
                      timezone_name=kwargs.get('timezone_name', 'UTC'))


def test_startup_and_manual_wakes_wait_until_exact_daily_slot():
    cycle, callback = ScheduledWorkerCycle(), Mock(return_value='done')
    first = step(cycle, START, callback)
    assert first.status == 'waiting'
    slot = first.next_run
    for seconds in (1, 100, 3599):
        assert step(cycle, START + timedelta(seconds=seconds), callback).status == 'waiting'
    callback.assert_not_called()
    result = step(cycle, slot + timedelta(seconds=10), callback)
    callback.assert_called_once_with(slot, slot + timedelta(seconds=10))
    assert result.status == 'attempted' and result.outcome == 'done'
    assert result.next_run == slot + timedelta(days=1)
    assert step(cycle, slot + timedelta(seconds=11), callback).status == 'waiting'
    callback.assert_called_once()


def test_missed_slot_is_skipped_without_catchup():
    cycle, callback = ScheduledWorkerCycle(), Mock()
    slot = step(cycle, START, callback).next_run
    result = step(cycle, slot + timedelta(seconds=60), callback)
    assert result.status == 'missed_slot_skipped'
    assert result.next_run == slot + timedelta(days=1)
    callback.assert_not_called()


def test_restart_at_due_time_does_not_catch_up():
    callback = Mock()
    cycle = ScheduledWorkerCycle()
    slot = step(cycle, START, callback).next_run
    result = step(ScheduledWorkerCycle(), slot, callback)
    assert result.status == 'waiting'
    assert result.next_run == slot + timedelta(days=1)
    callback.assert_not_called()


def test_callback_failure_advances_without_retry():
    cycle, callback = ScheduledWorkerCycle(), Mock(side_effect=RuntimeError('uncertain'))
    slot = step(cycle, START, callback).next_run
    with pytest.raises(RuntimeError, match='uncertain'):
        step(cycle, slot, callback)
    assert cycle.next_run == slot + timedelta(days=1)
    assert step(cycle, slot + timedelta(seconds=1), callback).status == 'waiting'
    callback.assert_called_once()


def test_schedule_change_recalculates_future_slot_and_does_not_dispatch():
    cycle, callback = ScheduledWorkerCycle(), Mock()
    step(cycle, START, callback)
    result = step(cycle, START + timedelta(hours=1), callback, local_time='01:30')
    assert result.next_run == datetime(2026, 10, 25, 1, 30, tzinfo=UTC)
    callback.assert_not_called()


def test_backward_clock_recalculates_future_without_replay():
    cycle, callback = ScheduledWorkerCycle(), Mock()
    slot = step(cycle, START, callback).next_run
    step(cycle, slot, callback)
    step(cycle, START, callback)
    # Memory may schedule that wall time again, but durable slot claiming must
    # reject a repeated local date before any collection or move.
    assert cycle.next_run == slot
    callback.assert_called_once()


@pytest.mark.parametrize('kwargs', [{'now': datetime(2026, 1, 1)}, {'local_time': 'bad'},
                                  {'timezone_name': 'unknown/zone'}, {'run_due': None}])
def test_invalid_cycle_input_never_calls_worker(kwargs):
    callback = Mock()
    values = dict(now=START, local_time='02:00', timezone_name='UTC', run_due=callback)
    values.update(kwargs)
    with pytest.raises(ValueError):
        ScheduledWorkerCycle().step(**values)
    callback.assert_not_called()
