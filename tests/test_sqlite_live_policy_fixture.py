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
    assert result.testsRun==3 and not result.skipped
