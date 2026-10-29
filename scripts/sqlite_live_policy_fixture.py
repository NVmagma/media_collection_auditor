"""Initial live policy against marked disposable media and private HTTP only."""
from datetime import timedelta
import json
import sys
import unittest
from unittest.mock import patch
from app.sqlite_live_policy import validate_initial_live_policy,DISABLED
from app.sqlite_operation_coordinator import INTENTS_KEY
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
        import app.sqlite_scheduled_routed_batch as batch
        original=batch._move
        self.move_failure=None
        def observed_move(**kwargs):
            try:return original(**kwargs)
            except Exception as error:
                # Fixed categories only: no exception text, paths, titles or URLs.
                cause=error
                while cause.__cause__ is not None:cause=cause.__cause__
                frame=error.__traceback__;functions=[]
                while frame is not None:
                    functions.append(frame.tb_frame.f_code.co_name);frame=frame.tb_next
                stage=('atomic_rename' if '_renameat2' in functions else
                       'parent_sync' if 'fsync' in functions else 'guarded_move')
                codes={'Atomic no-replace rename unsupported':'atomic_rename_unsupported',
                    'Configured stage root changed':'stage_root_changed',
                    'Planned source title changed':'source_identity_changed',
                    'Title location ambiguous or replaced':'title_identity_or_location_changed',
                    'Fresh decision unavailable or changed':'protection_decision_changed_or_unavailable',
                    'Rename mount binding changed':'mount_binding_changed',
                    'Rename requires one observed mount and device':'mount_or_device_crossing'}
                self.move_failure={'category':stage,'code':codes.get(str(error),'unclassified_guard_failure'),
                    'error_type':type(error).__name__,
                    'errno':cause.errno if isinstance(cause,OSError) else None}
                raise
        with patch.object(batch,'_move',observed_move):
            return _configured_cycle_step(cycle=self.case.cycle,settings=self.values,
                now=self.case.slot+timedelta(seconds=1),clock=lambda:NOW)

    def test_one_global_move_preserves_other_library_and_retained_json(self):
        result=self.run_due()
        self.assertEqual(len(result.outcome['completed']),1,json.dumps({
            'worker_status':result.outcome.get('status'),'worker_reason':result.outcome.get('reason'),
            'move_failure':self.move_failure,
            'source_present':self.case.layout.case.fixture.fixture.path(0,'transient').exists(),
            'destination_present':self.case.layout.case.fixture.fixture.path(0,'holding').exists(),
            'pending_operation_present':INTENTS_KEY in self.case.layout.store.load_with_revision()[0]}))
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

    def test_unsupported_atomic_rename_retains_intent_and_source_without_fallback(self):
        import errno
        import app.sqlite_scheduled_routed_batch as batch
        from app.sqlite_operation_coordinator import INTENTS_KEY
        def unsupported(*args):
            raise RuntimeError('Atomic no-replace rename unsupported') from OSError(errno.EOPNOTSUPP,'fixture')
        with patch.object(batch,'rename_directory_noreplace_at',unsupported):
            result=self.run_due()
        self.assertEqual(result.outcome['status'],'stopped')
        self.assertEqual(self.move_failure['code'],'atomic_rename_unsupported')
        self.assertEqual(len(result.outcome['completed']),0)
        self.assertIn(INTENTS_KEY,self.case.layout.store.load_with_revision()[0])
        self.assertTrue(self.case.layout.case.fixture.fixture.path(0,'transient').is_dir())
        self.assertFalse(self.case.layout.case.fixture.fixture.path(0,'holding').exists())
        self.assertEqual(self.case.source.read_bytes(),self.case.original_json)

    def test_preview_activation_still_refuses_live_values(self):
        from app.sqlite_backend_gate import require_sqlite_production_activation
        with self.assertRaises(RuntimeError):require_sqlite_production_activation(settings=self.values)
        self.assertEqual(self.case.layout.case.server.calls,[])
        self.assertFalse(self.case.layout.claims())


def main():
    if sys.argv[1:] not in ([],['--move-only']):raise SystemExit('Known fixture mode required')
    suite=(unittest.defaultTestLoader.loadTestsFromName(
        'test_one_global_move_preserves_other_library_and_retained_json',InitialLivePolicyTests)
        if sys.argv[1:]==['--move-only'] else unittest.defaultTestLoader.loadTestsFromTestCase(InitialLivePolicyTests))
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful():raise SystemExit(1)
    print(json.dumps({'status':'initial_live_policy_fixture_verified','tests':result.testsRun,
        'fixture_only':True,'production_activation':'disabled','production_authorized':False,
        'initial_maximum_actions':1,'permanent_deletion_enabled':False}))

if __name__=='__main__':main()
