"""Latest-state recovery against new prepared Linux fixture directories only."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from app import sqlite_release_recovery as recovery
from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_disposable_cutover_rehearsal import _json_restart
from app.sqlite_lock import _exclusive_lock, state_writer_lock
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_release_preparation import prepare_release_state, COMPLETE
from app.state_store import GuardedSQLiteStateStore
from scripts.sqlite_release_preparation_fixture import fixture_state


@unittest.skipUnless(sys.platform == 'linux', 'Linux prepared-release recovery')
class ReleaseRecoveryFixtureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix='release-recovery.')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source, self.control = self.root / 'source.json', self.root / 'control'
        self.original = json.dumps(fixture_state(), ensure_ascii=True).encode('ascii') + b'\n'
        self.source.write_bytes(self.original)
        prepare_release_state(source=self.source, control_directory=self.control,
            expected_source_sha256=hashlib.sha256(self.original).hexdigest())
        self.store = GuardedSQLiteStateStore(self.control / 'state.db')
        session = RevisionedAuditSession(self.store)
        session.state['queued']['Fixture Movie'] = session.state['first_seen'].pop('Fixture Movie')
        session.checkpoint()
        session.state['unknown']['newest'] = 'advanced history'
        session.checkpoint()
        self.state, self.revision = self.store.load_with_revision()
        self.name = 'rollback-candidate-current.json'

    def export(self, name=None):
        return recovery.export_release_candidate(source=self.source,
            control_directory=self.control, candidate_name=name or self.name)

    def inspect(self, name=None):
        return recovery.inspect_release_candidate(source=self.source,
            control_directory=self.control, candidate_name=name or self.name)

    def test_advanced_export_preserves_latest_clocks_arr_unknowns_and_json_restart(self):
        report = self.export()
        self.assertEqual(report['revision'], 2)
        self.assertFalse(report['restore_performed'])
        self.assertFalse(report['production_authorized'])
        self.assertNotIn('Fixture Movie', json.dumps(report))
        self.assertEqual(json.loads((self.control / self.name).read_bytes()), self.state)
        self.assertEqual(self.inspect()['status'], 'release_candidate_current_advisory_only')
        _json_restart(self.root, self.control / self.name, self.state)
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(self.store.load_with_revision(), (self.state, 2))

    def test_stale_candidate_refused_after_new_checkpoint(self):
        self.export(); before = (self.control / self.name).read_bytes()
        session = RevisionedAuditSession(self.store)
        session.state['unknown']['later'] = True; session.checkpoint()
        self.assertEqual(self.inspect()['status'], 'blocked')
        self.assertEqual((self.control / self.name).read_bytes(), before)
        self.assertEqual(self.export('rollback-candidate-newer.json')['revision'], 3)

    def test_same_revision_raw_mutation_cannot_reuse_candidate(self):
        self.export()
        with closing(sqlite3.connect(self.control / 'state.db')) as connection, connection:
            connection.execute("UPDATE extra_state SET value_json='{}' WHERE key='unknown'")
        # A transaction context does not close SQLite's file descriptor. Check
        # deterministic closure before inspection/cleanup, without waiting for GC.
        with self.assertRaises(sqlite3.ProgrammingError):
            connection.execute('SELECT 1')
        self.assertEqual(self.inspect()['status'], 'blocked')

    def test_pending_operation_refused_before_any_export_request(self):
        session = RevisionedAuditSession(self.store)
        session.state[INTENTS_KEY] = {}; session.checkpoint()
        with self.assertRaisesRegex(RuntimeError, 'Unresolved SQLite operation'): self.export()
        self.assertFalse((self.control / (self.name + '.request.json')).exists())
        self.assertIn(INTENTS_KEY, self.store.load_with_revision()[0])

    def test_existing_candidate_or_partial_request_is_never_overwritten(self):
        path = self.control / self.name; path.write_bytes(b'preserve')
        with self.assertRaisesRegex(RuntimeError, 'Existing recovery artifact'): self.export()
        self.assertEqual(path.read_bytes(), b'preserve')

    def test_identical_database_replacement_is_not_adopted(self):
        path = self.control / 'state.db'; raw = path.read_bytes()
        path.rename(self.control / 'retained.db'); path.write_bytes(raw)
        with self.assertRaisesRegex(RuntimeError, 'database identity changed'): self.export()

    def test_changed_retained_json_source_blocks_export(self):
        self.source.write_bytes(self.original + b' ')
        with self.assertRaisesRegex(RuntimeError, 'preparation binding mismatch'): self.export()

    def test_incomplete_or_corrupt_preparation_receipt_blocks_export(self):
        receipt = self.control / COMPLETE
        parsed = json.loads(receipt.read_bytes()); parsed['backup_verified'] = False
        receipt.write_text(json.dumps(parsed))
        with self.assertRaisesRegex(RuntimeError, 'preparation binding mismatch'): self.export()
        receipt.unlink()
        with self.assertRaises(FileNotFoundError): self.export()

    def test_shared_source_and_control_locks_block_export(self):
        for lock in (state_writer_lock(self.source),
                _exclusive_lock(self.control / '.sqlite_runner.lock', 'fixture')):
            with lock:
                with self.assertRaises(RuntimeError): self.export()
        self.assertFalse((self.control / self.name).exists())

    def test_partial_candidate_retained_without_completion_or_replay(self):
        write = recovery._write_private
        def partial(parent, name, raw):
            if name != self.name: return write(parent, name, raw)
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=parent)
            try: os.write(fd, raw[:7]); os.fsync(fd)
            finally: os.close(fd)
            raise OSError('fixture partial export')
        with patch.object(recovery, '_write_private', partial):
            with self.assertRaises(OSError): self.export()
        self.assertFalse((self.control / (self.name + '.complete.json')).exists())
        with self.assertRaises(RuntimeError): self.export()
        with self.assertRaises(FileNotFoundError): self.inspect()

    def test_concurrent_checkpoint_during_export_prevents_completion(self):
        write = recovery._write_private
        def advance(parent, name, raw):
            write(parent, name, raw)
            if name == self.name:
                session = RevisionedAuditSession(self.store)
                session.state['unknown']['competing_writer'] = True; session.checkpoint()
        with patch.object(recovery, '_write_private', advance):
            with self.assertRaises(RuntimeError): self.export()
        self.assertFalse((self.control / (self.name + '.complete.json')).exists())
        self.assertTrue(self.store.load_with_revision()[0]['unknown']['competing_writer'])

    def test_control_replacement_never_writes_replacement_tree(self):
        write = recovery._write_private
        retained = self.root / 'retained'
        def replace(parent, name, raw):
            write(parent, name, raw)
            if name == self.name:
                self.control.rename(retained); self.control.mkdir(mode=0o700)
                (self.control / 'sentinel').write_bytes(b'preserve')
        with patch.object(recovery, '_write_private', replace):
            with self.assertRaisesRegex(RuntimeError, 'control directory changed'): self.export()
        self.assertEqual([p.name for p in self.control.iterdir()], ['sentinel'])
        self.assertFalse((retained / (self.name + '.complete.json')).exists())

    def test_symlink_and_hardlink_candidates_are_refused(self):
        self.export(); candidate = self.control / self.name
        retained = self.control / 'retained-candidate.json'; candidate.rename(retained)
        candidate.symlink_to(retained)
        with self.assertRaises(OSError): self.inspect()
        candidate.unlink(); os.link(retained, candidate)
        with self.assertRaises(RuntimeError): self.inspect()

    def test_escaping_or_non_candidate_names_refused_without_writes(self):
        before = sorted(p.name for p in self.control.iterdir())
        for name in ('../state.json', 'state.db', '/tmp/escape.json'):
            with self.assertRaises(ValueError): self.export(name)
        self.assertEqual(sorted(p.name for p in self.control.iterdir()), before)

    def test_actual_sigkill_after_candidate_never_looks_complete_or_replays(self):
        code = '''
import os,signal,sys
from app import sqlite_release_recovery as r
write=r._write_private
def kill(parent,name,payload):
    write(parent,name,payload)
    if name==sys.argv[3]: os.kill(os.getpid(),signal.SIGKILL)
r._write_private=kill
r.export_release_candidate(source=sys.argv[1],control_directory=sys.argv[2],candidate_name=sys.argv[3])
'''
        result = subprocess.run([sys.executable, '-B', '-c', code,
            str(self.source), str(self.control), self.name], capture_output=True, timeout=30)
        self.assertEqual(result.returncode, -signal.SIGKILL)
        with self.assertRaises(FileNotFoundError): self.inspect()
        with self.assertRaises(RuntimeError): self.export()
        self.assertEqual(self.store.load_with_revision(), (self.state, self.revision))

    def test_actual_cli_export_inspection_and_redacted_failure(self):
        args = ['--source', str(self.source), '--control-directory', str(self.control), '--candidate-name', self.name]
        for action in ('export', 'inspect'):
            result = subprocess.run([sys.executable, '-B', '-m', 'app.sqlite_release_recovery', action, *args],
                capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertNotIn('Fixture Movie', result.stdout + result.stderr)
        result = subprocess.run([sys.executable, '-B', '-m', 'app.sqlite_release_recovery', 'export', *args],
            capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)['status'], 'release_recovery_blocked')
        self.assertNotIn('Traceback', result.stderr)

    def test_candidate_mutation_during_completion_is_not_reported_current(self):
        write = recovery._write_private
        def change(parent, name, raw):
            write(parent, name, raw)
            if name == self.name + '.complete.json':
                (self.control / self.name).write_bytes(b'{}')
        with patch.object(recovery, '_write_private', change):
            with self.assertRaisesRegex(RuntimeError, 'changed after publication'): self.export()
        with self.assertRaises(RuntimeError): self.inspect()

    def test_identical_candidate_replacement_during_inspection_is_refused(self):
        self.export()
        read = recovery._local
        replaced = []
        def replace(parent, name):
            result = read(parent, name)
            if name == self.name + '.complete.json' and not replaced:
                replaced.append(True)
                path = self.control / self.name
                raw = path.read_bytes(); path.rename(self.control / 'retained.json'); path.write_bytes(raw)
            return result
        with patch.object(recovery, '_local', replace):
            with self.assertRaisesRegex(RuntimeError, 'changed during inspection'): self.inspect()


def retained_evidence():
    root = Path(tempfile.mkdtemp(prefix='recovery-evidence.'))
    source, control = root / 'source.json', root / 'control'
    raw = json.dumps(fixture_state()).encode(); source.write_bytes(raw)
    prepare_release_state(source=source, control_directory=control, expected_source_sha256=hashlib.sha256(raw).hexdigest())
    store = GuardedSQLiteStateStore(control / 'state.db')
    session = RevisionedAuditSession(store)
    session.state['unknown']['latest'] = True; session.checkpoint()
    recovery.export_release_candidate(source=source, control_directory=control, candidate_name='rollback-candidate-earlier.json')
    session.state['unknown']['newest'] = True; session.checkpoint()
    if recovery.inspect_release_candidate(source=source, control_directory=control,
            candidate_name='rollback-candidate-earlier.json')['status'] != 'blocked':
        raise RuntimeError('Stale retained recovery candidate accepted')
    recovery.export_release_candidate(source=source, control_directory=control, candidate_name='rollback-candidate-latest.json')
    return root.name


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(ReleaseRecoveryFixtureTests))
    if not result.wasSuccessful() or result.testsRun != 18 or result.skipped:
        raise SystemExit(1)
    print(json.dumps({'status': 'release_recovery_verified', 'tests': result.testsRun,
        'retained_evidence_directory': retained_evidence(), 'fixture_only': True,
        'production_authorized': False, 'production_activation': 'disabled'}))
