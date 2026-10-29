"""Initial live policy against marked disposable media and private HTTP only."""
from datetime import timedelta
import json
import sys
import unittest
from app.sqlite_live_policy import validate_initial_live_policy,DISABLED
from app.sqlite_scheduled_production import _configured_cycle_step
from app.sqlite_scheduled_worker_cycle import ScheduledWorkerCycle
from scripts.sqlite_scheduled_runtime_fixture import ScheduledRuntimeFixtureTests
from scripts.sqlite_scheduled_configured_slot_fixture import NOW


@unittest.skipUnless(sys.platform=='linux','Linux no-replace rename acceptance')
class InitialLivePolicyTests(unittest.TestCase):
    def setUp(self):
        self.case=ScheduledRuntimeFixtureTests();self.case.setUp();self.addCleanup(self.case.doCleanups)
        self.values=dict(self.case.values)
        self.values.update(AUDITOR_STATE_BACKEND='sqlite',DRY_RUN='false',READ_ONLY_API_SERVICE='false',
            MAX_ACTIONS_PER_RUN='1',**{key:'false' for key in DISABLED})

    def run_due(self):
        validate_initial_live_policy(self.values)
        return _configured_cycle_step(cycle=self.case.cycle,settings=self.values,
            now=self.case.slot+timedelta(seconds=1),clock=lambda:NOW)

    def test_one_global_move_preserves_other_library_and_retained_json(self):
        result=self.run_due()
        self.assertEqual(len(result.outcome['completed']),1)
        self.assertTrue(self.case.layout.case.fixture.fixture.path(1,'transient').is_dir())
        self.assertEqual(self.case.source.read_bytes(),self.case.original_json)
        calls=len(self.case.layout.case.server.calls)
        self.assertEqual(self.case.step(self.case.slot+timedelta(seconds=2)).status,'waiting')
        self.assertEqual(len(self.case.layout.case.server.calls),calls)

    def test_unsafe_flags_block_before_claim_collection_or_move(self):
        for key in DISABLED:
            with self.subTest(setting=key):
                self.values[key]='true'
                with self.assertRaises(ValueError):self.run_due()
                self.values[key]='false'
        self.assertEqual(self.case.layout.case.server.calls,[])
        self.assertFalse(self.case.layout.claims())
        self.assertEqual(self.case.layout.store.load_with_revision(),self.case.layout.before)

    def test_preview_activation_still_refuses_live_values(self):
        from app.sqlite_backend_gate import require_sqlite_production_activation
        with self.assertRaises(RuntimeError):require_sqlite_production_activation(settings=self.values)
        self.assertEqual(self.case.layout.case.server.calls,[])
        self.assertFalse(self.case.layout.claims())


def main():
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(InitialLivePolicyTests))
    if not result.wasSuccessful():raise SystemExit(1)
    print(json.dumps({'status':'initial_live_policy_fixture_verified','tests':result.testsRun,
        'fixture_only':True,'production_activation':'disabled','production_authorized':False,
        'initial_maximum_actions':1,'permanent_deletion_enabled':False}))

if __name__=='__main__':main()
