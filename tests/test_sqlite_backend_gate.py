"""Production audit entry point must never silently select experimental SQLite."""

import pytest

from app.sqlite_backend_gate import require_json_backend


def test_default_json_backend_is_allowed():
    assert require_json_backend("json") is None


@pytest.mark.parametrize("value", ["sqlite", "SQLite", "SQLITE", "", "auto", "json,sqlite"])
def test_unapproved_backends_fail_closed(value):
    with pytest.raises(RuntimeError, match="SQLite production activation is disabled"):
        require_json_backend(value)


@pytest.mark.parametrize("backend", ["sqlite", "auto", "SQLite", ""])
def test_real_audit_entrypoint_rejects_backend_before_side_effects(monkeypatch, backend):
    """Rejected backend must not create directories, lock, or start an audit."""
    import sys
    from pathlib import Path
    from unittest.mock import Mock

    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "app"))
    import collection_auditor as auditor
    import sqlite_lock

    mkdir = Mock(side_effect=AssertionError("unexpected directory creation"))
    lock = Mock(side_effect=AssertionError("unexpected lock acquisition"))
    audit = Mock(side_effect=AssertionError("unexpected audit dispatch"))
    monkeypatch.setattr(auditor.os, "makedirs", mkdir)
    monkeypatch.setattr(sqlite_lock, "audit_run_lock", lock)
    monkeypatch.setattr(auditor, "_run_once_locked", audit)
    monkeypatch.setenv("AUDITOR_STATE_BACKEND", backend)

    with pytest.raises(RuntimeError, match="SQLite production activation is disabled"):
        auditor.run_once()
    mkdir.assert_not_called()
    lock.assert_not_called()
    audit.assert_not_called()


def test_candidate_production_scheduler_is_sealed_before_all_side_effects(monkeypatch):
    from app import sqlite_scheduled_production as worker
    from app.sqlite_scheduled_worker_cycle import ScheduledWorkerCycle
    from unittest.mock import Mock
    dispatch = Mock(side_effect=AssertionError('must stay sealed'))
    monkeypatch.setattr(worker, '_configured_cycle_step', dispatch)
    with pytest.raises(RuntimeError, match='SQLite production activation is disabled'):
        worker.production_cycle_step(cycle=ScheduledWorkerCycle(), settings={}, now=None)
    dispatch.assert_not_called()


def test_candidate_service_is_sealed_before_loading_settings():
    from app.sqlite_scheduled_service import run_daily_service
    from unittest.mock import Mock
    settings = Mock(side_effect=AssertionError('must stay sealed'))
    with pytest.raises(RuntimeError, match='SQLite production activation is disabled'):
        run_daily_service(apply_settings=settings)
    settings.assert_not_called()


def test_real_service_entrypoint_rejects_sqlite_before_thread_or_audit(tmp_path):
    import os
    from pathlib import Path
    import subprocess
    import sys
    root = Path(__file__).resolve().parents[1]
    (tmp_path / 'main.py').write_bytes((root / 'app/main.py').read_bytes())
    (tmp_path / 'sqlite_backend_gate.py').write_bytes((root / 'app/sqlite_backend_gate.py').read_bytes())
    (tmp_path / 'config_store.py').write_text('KEYS=set()\ndef load_config(): raise AssertionError("settings loaded")\n')
    (tmp_path / 'web.py').write_text('app=None\n')
    (tmp_path / 'integration_api.py').write_text('def read_only_service_enabled(): return False\n')
    (tmp_path / 'audit_history.py').write_text('''
def forbidden(*args): raise AssertionError("history touched")
new_record=finish_record=summarize_actions=forbidden
''')
    (tmp_path / 'run_control.py').write_text('''
def forbidden(*args): raise AssertionError("coordinator touched")
begin_run=finish_run=wait_for_run=forbidden
''')
    (tmp_path / 'collection_auditor.py').write_text('raise AssertionError("auditor imported")\n')
    child = '''
import runpy, threading
threading.Thread = lambda *a, **k: (_ for _ in ()).throw(AssertionError("thread started"))
try:
    runpy.run_path("main.py", run_name="__main__")
except RuntimeError as error:
    assert "SQLite production activation is disabled" in str(error)
    print("sealed")
else:
    raise AssertionError("gate bypassed")
'''
    env = dict(os.environ, AUDITOR_STATE_BACKEND='sqlite', PYTHONPATH=str(tmp_path))
    result = subprocess.run([sys.executable, '-B', '-c', child], cwd=tmp_path,
        env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'sealed'
