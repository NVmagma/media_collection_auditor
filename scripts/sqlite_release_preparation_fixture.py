"""Backup/migration preparation against new disposable Linux state only."""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from app import sqlite_release_preparation as preparation
from app.sqlite_lock import state_writer_lock
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_state import SECTIONS
from app.state_store import GuardedSQLiteStateStore


def fixture_state():
    state = {section: {} for section in SECTIONS}
    state['first_seen']['Fixture Movie'] = '2024-01-01T00:00:00'
    state['keep_seen']['TV/Fixture Show'] = '2024-02-01T00:00:00'
    state['arr_sync_pending']['Fixture Pending'] = {
        'stage': 'holding', 'root': '/synthetic/holding', 'monitored': False,
        'service': 'radarr', 'title_id': 17, 'unknown_retry_metadata': {'attempts': 1}}
    state['unknown'] = {'unicode': 'caf\u00e9', 'nested': [1, None, False]}
    return state


@unittest.skipUnless(sys.platform == 'linux', 'Linux descriptor-bound preparation')
class ReleasePreparationFixtureTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory(prefix='release-preparation.')
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.source = self.root / 'legacy.json'
        self.control = self.root / 'control'
        self.state = fixture_state()
        self.original = json.dumps(self.state, ensure_ascii=True).encode('ascii') + b'\n'
        self.source.write_bytes(self.original)
        self.digest = hashlib.sha256(self.original).hexdigest()

    def run_preparation(self, **kwargs):
        return preparation.prepare_release_state(source=kwargs.pop('source', self.source),
            control_directory=kwargs.pop('control_directory', self.control),
            expected_source_sha256=kwargs.pop('expected_source_sha256', self.digest), **kwargs)

    def assert_incomplete(self):
        self.assertTrue((self.control / preparation.REQUEST).is_file())
        self.assertFalse((self.control / preparation.COMPLETE).exists())

    def test_backup_and_database_preserve_all_state_without_activation(self):
        report = self.run_preparation()
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual((self.control / preparation.BACKUP).read_bytes(), self.original)
        self.assertEqual(GuardedSQLiteStateStore(self.control / 'state.db').load_with_revision(), (self.state, 0))
        self.assertEqual(self.control.stat().st_mode & 0o777, 0o700)
        self.assertEqual((self.control / 'state.db').stat().st_mode & 0o777, 0o600)
        self.assertFalse(report['production_authorized'])
        self.assertFalse(report['writer_quiescence_verified'])
        self.assertEqual(report['status'], 'release_state_prepared_not_activated')
        self.assertNotIn('Fixture Movie', json.dumps(report))
        self.assertEqual(json.loads((self.control / preparation.COMPLETE).read_bytes()), report)

    def test_existing_control_never_overwritten_or_adopted(self):
        self.control.mkdir(); sentinel = self.control / 'state.db'; sentinel.write_bytes(b'existing')
        with self.assertRaises(FileExistsError): self.run_preparation()
        self.assertEqual(list(self.control.iterdir()), [sentinel])
        self.assertEqual(sentinel.read_bytes(), b'existing')

    def test_success_cannot_be_replayed(self):
        self.run_preparation()
        files = {p.name: p.read_bytes() for p in self.control.iterdir()}
        with self.assertRaises(FileExistsError): self.run_preparation()
        self.assertEqual({p.name: p.read_bytes() for p in self.control.iterdir()}, files)

    def test_stale_hash_does_not_create_destination(self):
        with self.assertRaisesRegex(RuntimeError, 'hash mismatch'):
            self.run_preparation(expected_source_sha256='0' * 64)
        self.assertFalse(self.control.exists())

    def test_missing_sections_duplicate_keys_and_nonfinite_unknowns_rejected(self):
        invalid = (b'{"first_seen":{}}',
            self.original.replace(b'"unknown":', b'"first_seen":{}, "unknown":'),
            self.original.replace(b'"nested": [1, null, false]', b'"nested": [NaN]'))
        for raw in invalid:
            with self.subTest(raw=raw[:20]):
                self.source.write_bytes(raw)
                with self.assertRaises((RuntimeError, ValueError)):
                    self.run_preparation(expected_source_sha256=hashlib.sha256(raw).hexdigest())
                self.assertFalse(self.control.exists())

    def test_pending_operation_presence_refused_before_destination_creation(self):
        self.state[INTENTS_KEY] = {}
        raw = json.dumps(self.state).encode(); self.source.write_bytes(raw)
        with self.assertRaisesRegex(RuntimeError, 'Unresolved operation'):
            self.run_preparation(expected_source_sha256=hashlib.sha256(raw).hexdigest())
        self.assertFalse(self.control.exists())

    def test_symlink_and_hardlink_sources_are_refused(self):
        alias = self.root / 'alias.json'; alias.symlink_to(self.source)
        with self.assertRaises(OSError): self.run_preparation(source=alias)
        alias.unlink(); os.link(self.source, alias)
        with self.assertRaises(RuntimeError): self.run_preparation()
        self.assertFalse(self.control.exists())
        self.assertEqual(self.source.read_bytes(), self.original)

    def test_fifo_source_is_nonblocking_and_refused(self):
        fifo = self.root / 'input.fifo'; os.mkfifo(fifo)
        with self.assertRaises(RuntimeError): self.run_preparation(source=fifo)
        self.assertFalse(self.control.exists())

    def test_aliased_parent_is_refused(self):
        alias = self.root / 'alias'; alias.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(OSError): self.run_preparation(control_directory=alias / 'control')
        self.assertFalse(self.control.exists())

    def test_writer_lock_contention_blocks_all_destination_writes(self):
        with state_writer_lock(self.source):
            with self.assertRaises(RuntimeError): self.run_preparation()
        self.assertFalse(self.control.exists())

    def test_writable_control_ancestor_refused_without_permission_changes(self):
        self.root.chmod(0o777)
        with self.assertRaisesRegex(RuntimeError, 'Protected release control ancestors'):
            self.run_preparation()
        self.assertFalse(self.control.exists())
        self.assertEqual(self.root.stat().st_mode & 0o777, 0o777)

    def test_identical_source_replacement_after_backup_is_refused(self):
        write = preparation._write_private
        def replace(parent, name, payload):
            write(parent, name, payload)
            if name == preparation.BACKUP:
                self.source.rename(self.root / 'retained-original.json')
                self.source.write_bytes(self.original)
        with patch.object(preparation, '_write_private', replace):
            with self.assertRaisesRegex(RuntimeError, 'source identity/content changed'):
                self.run_preparation()
        self.assert_incomplete()
        self.assertFalse((self.control / 'state.db').exists())

    def test_partial_backup_retained_without_database_or_replay(self):
        write = preparation._write_private
        def partial(parent, name, payload):
            if name != preparation.BACKUP: return write(parent, name, payload)
            fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=parent)
            try: os.write(fd, payload[:9]); os.fsync(fd)
            finally: os.close(fd)
            raise OSError('fixture partial backup')
        with patch.object(preparation, '_write_private', partial):
            with self.assertRaises(OSError): self.run_preparation()
        self.assert_incomplete()
        self.assertEqual((self.control / preparation.BACKUP).read_bytes(), self.original[:9])
        with self.assertRaises(FileExistsError): self.run_preparation()

    def test_control_replacement_during_sqlite_write_never_writes_replacement(self):
        write = preparation.write_offline_snapshot
        retained = self.root / 'retained-control'
        def replace(state, database):
            self.control.rename(retained)
            self.control.mkdir(); (self.control / 'sentinel').write_bytes(b'unchanged')
            write(state, database)
        with patch.object(preparation, 'write_offline_snapshot', replace):
            with self.assertRaisesRegex(RuntimeError, 'control directory changed'):
                self.run_preparation()
        self.assertEqual([p.name for p in self.control.iterdir()], ['sentinel'])
        self.assertEqual((self.control / 'sentinel').read_bytes(), b'unchanged')
        self.assertTrue((retained / 'state.db').exists())
        self.assertFalse((retained / preparation.COMPLETE).exists())

    def test_changed_request_prevents_completion_receipt(self):
        write = preparation._write_private
        def change(parent, name, payload):
            write(parent, name, payload)
            if name == preparation.BACKUP:
                (self.control / preparation.REQUEST).write_bytes(b'{}')
        with patch.object(preparation, '_write_private', change):
            with self.assertRaisesRegex(RuntimeError, 'output changed'):
                self.run_preparation()
        self.assert_incomplete()

    def test_wrong_database_parity_never_writes_completion(self):
        write = preparation.write_offline_snapshot
        def wrong(state, database):
            state = dict(state, unknown={'wrong': True}); write(state, database)
        with patch.object(preparation, 'write_offline_snapshot', wrong):
            with self.assertRaisesRegex(RuntimeError, 'parity/revision mismatch'):
                self.run_preparation()
        self.assert_incomplete()

    def test_actual_sigkill_after_database_retains_backup_and_blocks_replay(self):
        code = '''
import os,signal,sys
from app import sqlite_release_preparation as p
write=p.write_offline_snapshot
def kill(state,database):
    write(state,database)
    os.kill(os.getpid(),signal.SIGKILL)
p.write_offline_snapshot=kill
p.prepare_release_state(source=sys.argv[1],control_directory=sys.argv[2],expected_source_sha256=sys.argv[3])
'''
        result = subprocess.run([sys.executable, '-B', '-c', code, str(self.source), str(self.control), self.digest],
            capture_output=True, timeout=30)
        self.assertEqual(result.returncode, -signal.SIGKILL)
        self.assert_incomplete()
        self.assertEqual((self.control / preparation.BACKUP).read_bytes(), self.original)
        self.assertTrue((self.control / 'state.db').exists())
        with self.assertRaises(FileExistsError): self.run_preparation()
        self.assertEqual(self.source.read_bytes(), self.original)

    def cli(self):
        return subprocess.run([sys.executable, '-B', '-m', 'app.sqlite_release_preparation',
            '--source', str(self.source), '--new-control-directory', str(self.control),
            '--expected-source-sha256', self.digest], capture_output=True, text=True, timeout=30)

    def test_actual_cli_prepares_only_and_redacts_title_payloads(self):
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['status'], 'release_state_prepared_not_activated')
        self.assertNotIn('Fixture Movie', result.stdout + result.stderr)
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(self.cli().returncode, 1)

    def test_actual_cli_failure_does_not_leak_duplicate_private_key(self):
        raw = b'{"secret-title-token":1,"secret-title-token":2}'
        self.source.write_bytes(raw); self.digest = hashlib.sha256(raw).hexdigest()
        result = self.cli()
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)['status'], 'release_preparation_blocked')
        self.assertNotIn('secret-title-token', result.stdout + result.stderr)
        self.assertFalse(self.control.exists())


def retained_evidence():
    root = Path(tempfile.mkdtemp(prefix='preparation-evidence.'))
    source = root / 'source.json'
    raw = json.dumps(fixture_state(), ensure_ascii=True).encode('ascii') + b'\n'
    source.write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    preparation.prepare_release_state(source=source, control_directory=root / 'prepared', expected_source_sha256=digest)
    def interrupt(state, database):
        database.write_bytes(b'fixture incomplete database')
        raise RuntimeError('fixture interrupted migration')
    with patch.object(preparation, 'write_offline_snapshot', interrupt):
        try:
            preparation.prepare_release_state(source=source, control_directory=root / 'interrupted', expected_source_sha256=digest)
        except RuntimeError:
            pass
        else:
            raise RuntimeError('Interrupted preparation unexpectedly succeeded')
    if (root / 'interrupted' / preparation.COMPLETE).exists() or source.read_bytes() != raw:
        raise RuntimeError('Retained preparation evidence changed')
    return root.name


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromTestCase(ReleasePreparationFixtureTests))
    if not result.wasSuccessful() or result.testsRun != 19 or result.skipped:
        raise SystemExit(1)
    evidence = retained_evidence()
    print(json.dumps({'status': 'release_preparation_verified', 'tests': result.testsRun,
        'retained_evidence_directory': evidence, 'fixture_only': True,
        'production_authorized': False, 'production_activation': 'disabled'}))
