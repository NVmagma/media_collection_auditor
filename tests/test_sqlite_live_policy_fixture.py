"""Keep the marked, real-rename initial live policy rehearsal in CI."""
import io
import sys
import unittest
import pytest
from scripts import sqlite_live_policy_fixture as fixture


@pytest.mark.skipif(sys.platform!='linux',reason='Linux atomic no-replace rename required')
def test_initial_live_policy_actual_disposable_worker():
    output=io.StringIO()
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(fixture.InitialLivePolicyTests)
    result=unittest.TextTestRunner(stream=output,verbosity=2).run(suite)
    assert result.wasSuccessful(),output.getvalue()
    assert result.testsRun==4 and not result.skipped


@pytest.mark.skipif(sys.platform!='linux',reason='Linux atomic no-replace rename required')
def test_capped_actual_move_updates_integrity_with_all_durable_checkpoints():
    import sqlite3
    from contextlib import closing
    from app.sqlite_live_integrity import initialize
    case=fixture.InitialLivePolicyTests();case.setUp()
    try:
        state,revision=case.case.layout.store.load_with_revision()
        path=case.case.layout.control/'state.db'
        with closing(sqlite3.connect(path)) as connection:
            connection.execute('BEGIN IMMEDIATE');initialize(connection,state=state,revision=revision);connection.commit()
        result=case.run_due()
        assert len(result.outcome['completed'])==1
        current,advanced=case.case.layout.store.load_with_revision()
        assert advanced==revision+3
        assert current['custom']==state['custom']
        assert case.case.source.read_bytes()==case.case.original_json
    finally:case.doCleanups()
