"""One revision for summary/widgets/dashboard; only new disposable SQLite files."""
from contextlib import closing
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from app.sqlite_snapshot_writer import write_offline_snapshot
from app.sqlite_store import SQLiteStateStore
from app.sqlite_tracking_view import capture_candidate_tracking_view, capture_candidate_dashboard_state
import app.sqlite_tracking_view as module


class TrackingViewFixtureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='tracking-view-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.database = self.root / 'state.db'
        self.state = {'first_seen': {'A': '2024-01-01', 'TV/B': '2024-01-02'},
            'queued': {'C': '2024-01-03'}, 'keep_seen': {}, 'in_removal': {},
            'arr_sync_pending': {}, 'unknown': {'token': 'fixture-private-token', 'path': '/fixture/private'}}
        write_offline_snapshot(self.state, self.database)

    def test_connections_close_before_replacement_without_garbage_collection(self):
        import sqlite3
        connect = sqlite3.connect
        held = []
        def record(*args, **kwargs):
            connection = connect(*args, **kwargs)
            held.append(connection)
            return connection
        try:
            with patch.object(sqlite3, 'connect', record):
                write_offline_snapshot(self.state, self.root / 'extra.db')
                SQLiteStateStore(self.database).load_with_revision()
                capture_candidate_tracking_view(self.database)
            self.assertTrue(held)
            for connection in held:
                with self.assertRaisesRegex(sqlite3.ProgrammingError, 'closed'):
                    connection.execute('SELECT 1')
        finally:
            for connection in held:
                connection.close()

    def test_one_capture_drives_summary_both_widgets_and_detached_dashboard(self):
        original = module.read_experimental_sqlite_dashboard_snapshot
        with patch.object(module, 'read_experimental_sqlite_dashboard_snapshot', wraps=original) as read:
            view = capture_candidate_tracking_view(self.database)
        self.assertEqual(read.call_count, 1)
        self.assertEqual(view['summary']['tracking_counts']['waiting'], 2)
        for key in ('summary', 'oldest_waiting', 'leaving_soon'):
            self.assertEqual(view[key]['state_revision'], view['state_revision'])
            self.assertEqual(view[key]['storage_authority'], 'sqlite_candidate')
        state = capture_candidate_dashboard_state(self.database)
        self.assertEqual(state, self.state)
        state['queued'].clear()
        self.assertEqual(capture_candidate_dashboard_state(self.database), self.state)

    def test_independent_process_checkpoint_invalidates_entire_response(self):
        original = module._project_tracking_status
        def update(capture):
            child = 'from app.sqlite_store import SQLiteStateStore; import sys; s=SQLiteStateStore(sys.argv[1]); state,r=s.load_with_revision(); state["queued"]["New"]="2024-02-01"; s.save_if_revision(state,r)'
            subprocess.run([sys.executable, '-B', '-c', child, str(self.database)], check=True, timeout=15)
            return original(capture)
        with patch.object(module, '_project_tracking_status', update):
            with self.assertRaisesRegex(RuntimeError, '^Candidate SQLite tracking view unavailable$'):
                capture_candidate_tracking_view(self.database)

    def test_identical_replacement_is_not_adopted(self):
        original = module._project_tracking_status
        def replace(capture):
            payload = self.database.read_bytes()
            self.database.rename(self.root / 'old.db')
            self.database.write_bytes(payload)
            return original(capture)
        with patch.object(module, '_project_tracking_status', replace):
            with self.assertRaises(RuntimeError):
                capture_candidate_tracking_view(self.database)

    def test_missing_database_never_uses_valid_json_or_creates_sqlite(self):
        self.database.unlink()
        (self.root / 'state.json').write_text(json.dumps(self.state))
        with self.assertRaises(RuntimeError):
            capture_candidate_tracking_view(self.database)
        self.assertFalse(self.database.exists())

    def test_pending_payload_and_unknown_secrets_never_escape_projection(self):
        store = SQLiteStateStore(self.database)
        state, revision = store.load_with_revision()
        state['sqlite_pending_operations'] = {'credential': 'fixture-private-token'}
        store.save_if_revision(state, revision)
        report = capture_candidate_tracking_view(self.database)
        self.assertTrue(report['summary']['pending_operation_present'])
        self.assertFalse(report['production_authorized'])
        self.assertNotIn('fixture-private-token', json.dumps(report))
        self.assertNotIn('/fixture/private', json.dumps(report))
        self.assertNotIn('credential', json.dumps(report))

    def test_symlink_database_is_refused_without_modifying_target(self):
        self.database.rename(self.root / 'target.db')
        target = self.root / 'target.db'
        before = target.read_bytes()
        self.database.symlink_to(target)
        with self.assertRaises(RuntimeError):
            capture_candidate_tracking_view(self.database)
        self.assertEqual(target.read_bytes(), before)

    def test_projection_failure_never_returns_partial_summary(self):
        with self.assertRaises(RuntimeError):
            capture_candidate_tracking_view(self.database, holding_days=0)
        self.assertEqual(SQLiteStateStore(self.database).load_with_revision()[0], self.state)

    def test_same_revision_raw_mutation_invalidates_capture(self):
        import sqlite3
        original = module._project_tracking_status
        def mutate(capture):
            # Write through the supported store, then restore only the revision
            # metadata: exact snapshot equality must still detect the mutation.
            store = SQLiteStateStore(self.database)
            state, revision = store.load_with_revision()
            state['queued']['Added'] = '2024-02-01'
            store.save_if_revision(state, revision)
            with closing(sqlite3.connect(self.database)) as connection, connection:
                connection.execute("UPDATE metadata SET value=? WHERE key='state_revision'", (str(revision),))
            return original(capture)
        with patch.object(module, '_project_tracking_status', mutate):
            with self.assertRaises(RuntimeError):
                capture_candidate_tracking_view(self.database)


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(TrackingViewFixtureTests))
    if not result.wasSuccessful() or result.testsRun != 9 or result.skipped:
        raise SystemExit(1)
    print(json.dumps({'status': 'candidate_tracking_views_verified', 'tests': result.testsRun,
        'fixture_only': True, 'production_authorized': False, 'production_activation': 'disabled'}))
