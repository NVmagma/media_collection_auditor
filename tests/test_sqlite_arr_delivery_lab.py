from pathlib import Path
from tests import test_sqlite_scheduled_gate6_lab as helper

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/sqlite_arr_delivery_lab.sh'


def test_slot_uses_only_new_fixture_and_fixed_atomic_module(tmp_path, monkeypatch):
    monkeypatch.setattr(helper, 'SCRIPT', SCRIPT)
    result, base, log = helper.run_lab(tmp_path)
    assert result.returncode == 0, result.stderr
    assert 'status=arr_delivery_acceptance_complete' in result.stdout
    assert 'scripts.sqlite_arr_delivery_fixture' in log.read_text()
    assert 'scripts.sqlite_scheduled_move_fixture' not in log.read_text()
    assert 'acceptance_scope=one_shot_arr_delivery_retained_pending' in result.stdout
    assert '--cap-drop\nALL' in log.read_text()
    assert '/var/run/docker.sock' not in log.read_text()
    assert (base / 'existing').read_text() == 'preserve'
    assert len(list(base.glob('arr-delivery.*'))) == 1
    assert log.read_text().endswith('rm\n--force\n' + helper.CONTAINER + '\n')


def test_slot_failure_does_not_report_success_and_removes_only_fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(helper, 'SCRIPT', SCRIPT)
    result, base, log = helper.run_lab(tmp_path, FIXTURE_START_FAIL='yes')
    assert result.returncode != 0
    assert 'status=arr_delivery_acceptance_complete' not in result.stdout
    assert log.read_text().endswith('rm\n--force\n' + helper.CONTAINER + '\n')
    assert (base / 'existing').read_text() == 'preserve'
