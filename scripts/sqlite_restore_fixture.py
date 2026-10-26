"""Disposable advanced-state restore, fresh JSON restart and crash refusal."""
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from tempfile import TemporaryDirectory, mkdtemp
import unittest
from unittest.mock import patch

from app import sqlite_disposable_restore as module
from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_disposable_cutover_rehearsal import _CHILD, rehearse_disposable_cutover
from app.sqlite_disposable_rollback import export_disposable_rollback_candidate
from app.sqlite_lock import _exclusive_lock
from app.sqlite_migration import create_offline_migration_snapshot
from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_state import SECTIONS
from app.state_store import GuardedSQLiteStateStore


def verify_json_restart(root, state_path, expected):
    digest = hashlib.sha256(json.dumps(expected, ensure_ascii=True, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode('ascii')).hexdigest()
    app = Path(module.__file__).resolve().parent
    env = {'PYTHONPATH': str(app.parent) + os.pathsep + str(app), 'STATE_FILE': str(state_path),
           'AUDITOR_STATE_BACKEND': 'json', 'DRY_RUN': 'true', 'PYTHONDONTWRITEBYTECODE': '1'}
    for mode in ('load', 'save', 'load'):
        child = subprocess.run([sys.executable, '-B', '-c', _CHILD, mode], env=env,
            cwd=root, capture_output=True, text=True, timeout=30)
        if child.returncode != 0 or 'PARITY=' + digest not in child.stdout.splitlines():
            raise RuntimeError('Fresh JSON restart parity failed')
    if json.loads(state_path.read_bytes()) != expected:
        raise RuntimeError('Restored JSON tracking changed')


def retained_evidence():
    base = Path(mkdtemp(prefix='restore-evidence.')).resolve()
    for name in ('completed', 'interrupted'):
        root = base / name
        rehearse_disposable_cutover(root=root)
        candidate = root / 'rollback-candidate-current.json'
        before = {path: path.read_bytes() for path in
            (root/'original.json', root/'original.backup.json', root/'state.db', candidate)}
        expected, _ = GuardedSQLiteStateStore(root/'state.db').load_with_revision()
        output = root / 'restored-state-current.json'
        arguments = dict(root=root, candidate_name=candidate.name, output_name=output.name)
        if name == 'completed':
            module.restore_disposable_json(**arguments)
            verify_json_restart(root, output, expected)
            if not (root/module.COMPLETE).is_file(): raise RuntimeError('Missing completion evidence')
        else:
            try:
                module.restore_disposable_json(**arguments, fault_at='after_publication')
            except RuntimeError:
                pass
            else:
                raise RuntimeError('Interrupted restore unexpectedly completed')
            if (root/module.COMPLETE).exists() or not (root/module.REQUEST).is_file():
                raise RuntimeError('Interrupted restore evidence invalid')
            try:
                module.restore_disposable_json(**arguments)
            except RuntimeError:
                pass
            else:
                raise RuntimeError('Interrupted restore was replayed')
        if any(path.read_bytes() != raw for path, raw in before.items()):
            raise RuntimeError('Retained source/backup/database changed')
    return base.name


class RestoreFixtureTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory(prefix='restore.')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        (self.root / '.sqlite_disposable_rehearsal').write_text('DISPOSABLE ONLY\n')
        self.source = self.root / 'original.json'; self.backup = self.root / 'original.backup.json'
        self.database = self.root / 'state.db'
        state = {section: {} for section in SECTIONS}
        state['first_seen'] = {'Movie': '2024-01-01T00:00:00', 'TV/Show': '2024-01-02T00:00:00'}
        state['extension'] = {'unicode': 'caf\u00e9', 'nested': [False, None, 3]}
        self.source.write_text(json.dumps(state))
        self.original = self.source.read_bytes()
        create_offline_migration_snapshot(self.source, self.backup, self.database)
        self.store = GuardedSQLiteStateStore(self.database)
        export_disposable_rollback_candidate(root=self.root, candidate_name='rollback-candidate-old.json')
        session = RevisionedAuditSession(self.store)
        session.state['queued']['Movie'] = session.state['first_seen'].pop('Movie')
        session.state['arr_sync_pending']['Movie'] = {'stage': 'holding', 'root': '/synthetic/holding',
            'service': 'radarr', 'title_id': 42, 'monitored': False}
        session.checkpoint()
        session.state['keep_seen']['TV/Show'] = session.state['first_seen'].pop('TV/Show')
        session.state['extension']['newer_history'] = 'retained'
        session.checkpoint()
        self.expected, self.revision = session.read_verified_snapshot()
        export_disposable_rollback_candidate(root=self.root, candidate_name='rollback-candidate-current.json')
        self.candidate = self.root / 'rollback-candidate-current.json'
        self.candidate_bytes = self.candidate.read_bytes()
        self.database_bytes = self.database.read_bytes()
        self.output = self.root / 'restored-state-current.json'

    def restore(self, **kwargs):
        return module.restore_disposable_json(root=self.root,
            candidate_name=kwargs.pop('candidate_name', self.candidate.name),
            output_name=self.output.name, **kwargs)

    def originals_intact(self):
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(self.backup.read_bytes(), self.original)
        self.assertEqual(self.candidate.read_bytes(), self.candidate_bytes)

    def blocked_retry(self):
        self.assertTrue((self.root / module.REQUEST).exists())
        before = self.output.read_bytes() if self.output.exists() else None
        with self.assertRaises(RuntimeError): self.restore()
        self.assertEqual(self.output.read_bytes() if self.output.exists() else None, before)

    def test_latest_advanced_snapshot_restores_and_survives_fresh_json_processes(self):
        result = self.restore()
        self.assertEqual(result['revision'], 2)
        self.assertEqual(self.output.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.output.stat().st_nlink, 1)
        self.assertEqual(json.loads(self.output.read_bytes()), self.expected)
        verify_json_restart(self.root, self.output, self.expected)
        self.assertEqual(json.loads(self.output.read_bytes()), self.expected)
        self.assertEqual(self.database.read_bytes(), self.database_bytes)
        self.originals_intact(); self.blocked_retry()

    def test_stale_candidate_cannot_create_output_or_request(self):
        with self.assertRaises(RuntimeError): self.restore(candidate_name='rollback-candidate-old.json')
        self.assertFalse(self.output.exists()); self.assertFalse((self.root / module.REQUEST).exists())
        self.originals_intact()

    def test_pending_sqlite_operation_blocks_restore(self):
        state, revision = self.store.load_with_revision(); state[INTENTS_KEY] = {}
        self.store.save_if_revision(state, revision)
        with self.assertRaises(RuntimeError): self.restore()
        self.assertFalse(self.output.exists()); self.assertFalse((self.root / module.REQUEST).exists())

    def test_existing_destination_is_never_overwritten(self):
        self.output.write_bytes(b'existing history')
        with self.assertRaises(RuntimeError): self.restore()
        self.assertEqual(self.output.read_bytes(), b'existing history')
        self.originals_intact()

    def test_live_or_escaping_output_names_are_rejected(self):
        for name in ('original.json', '/tmp/restored-state-live.json', '../restored-state-live.json',
                     'restored-state-dir/file.json'):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):
                    module.restore_disposable_json(root=self.root, candidate_name=self.candidate.name,
                                                  output_name=name)
        self.assertFalse((self.root / module.REQUEST).exists()); self.originals_intact()

    def test_destination_created_during_staging_is_never_overwritten(self):
        write = module._write_private
        def occupy(parent, name, payload):
            write(parent, name, payload)
            if name.startswith('.restore-staging-'): self.output.write_bytes(b'concurrent winner')
        with patch.object(module, '_write_private', occupy):
            with self.assertRaises(FileExistsError): self.restore()
        self.assertEqual(self.output.read_bytes(), b'concurrent winner')
        self.blocked_retry(); self.originals_intact()

    def test_candidate_symlink_is_refused(self):
        self.candidate.rename(self.root / 'saved-candidate.json')
        self.candidate.symlink_to(self.root / 'saved-candidate.json')
        with self.assertRaises(OSError): self.restore()
        self.assertFalse(self.output.exists())

    def stage_action(self, action):
        write = module._write_private
        def wrapped(parent, name, payload):
            write(parent, name, payload)
            if name.startswith('.restore-staging-'): action()
        with patch.object(module, '_write_private', wrapped):
            with self.assertRaises(RuntimeError): self.restore()
        self.assertFalse(self.output.exists()); self.blocked_retry()

    def test_identical_database_replacement_during_restore_is_not_adopted(self):
        def replace():
            old = self.root / 'held-original.db'
            self.database.rename(old); self.database.write_bytes(old.read_bytes())
        self.stage_action(replace)

    def test_sqlite_advance_during_staging_blocks_publication(self):
        def advance():
            state, revision = self.store.load_with_revision()
            state['extension']['later'] = True; self.store.save_if_revision(state, revision)
        self.stage_action(advance)

    def test_partial_staging_write_retains_request_and_refuses_retry(self):
        write = module._write_private
        def partial(parent, name, payload):
            if name.startswith('.restore-staging-'):
                write(parent, name, payload[:20]); raise RuntimeError('partial write')
            return write(parent, name, payload)
        with patch.object(module, '_write_private', partial):
            with self.assertRaises(RuntimeError): self.restore()
        self.assertFalse(self.output.exists()); self.blocked_retry(); self.originals_intact()

    def test_fault_after_publication_retains_unknown_outcome_without_replay(self):
        with self.assertRaises(RuntimeError): self.restore(fault_at='after_publication')
        self.assertTrue(self.output.exists()); self.assertFalse((self.root / module.COMPLETE).exists())
        self.blocked_retry(); self.originals_intact()

    def test_actual_sigkill_after_publication_keeps_request_and_prevents_replay(self):
        code = r'''
import os, signal, sys
from app import sqlite_disposable_restore as m
link = m.os.link
def kill_after_link(*args, **kwargs):
    link(*args, **kwargs)
    os.kill(os.getpid(), signal.SIGKILL)
m.os.link = kill_after_link
m.restore_disposable_json(root=sys.argv[1], candidate_name='rollback-candidate-current.json',
                         output_name='restored-state-current.json')
'''
        app = Path(module.__file__).resolve().parent
        env = dict(os.environ, PYTHONPATH=str(app.parent) + os.pathsep + str(app))
        child = subprocess.run([sys.executable, '-B', '-c', code, str(self.root)],
            env=env, cwd=self.root, capture_output=True, timeout=30)
        self.assertEqual(child.returncode, -signal.SIGKILL, child.stderr.decode())
        self.assertTrue(self.output.exists()); self.blocked_retry(); self.originals_intact()

    def test_backup_replacement_during_staging_blocks_publication(self):
        def replace():
            self.backup.rename(self.root / 'held-backup.json'); self.backup.write_bytes(self.original)
        self.stage_action(replace)

    def test_publication_sync_failure_is_not_reported_as_success(self):
        sync = module.os.fsync
        def fail(fd):
            if self.output.exists(): raise OSError('injected parent sync failure')
            return sync(fd)
        with patch.object(module.os, 'fsync', fail):
            with self.assertRaises(OSError): self.restore()
        self.assertTrue(self.output.exists()); self.blocked_retry(); self.originals_intact()

    def test_cooperating_json_writer_lock_blocks_before_request(self):
        with _exclusive_lock(self.source.with_name('original.json.migration.lock'), 'fixture busy'):
            with self.assertRaises(RuntimeError): self.restore()
        self.assertFalse((self.root / module.REQUEST).exists()); self.assertFalse(self.output.exists())

    def test_open_unlinked_fuse_retention_does_not_leave_a_second_link(self):
        descriptors = Path('/proc/self/fd')
        if not descriptors.is_dir(): descriptors = Path('/dev/fd')
        if not descriptors.is_dir(): self.skipTest('Process descriptor view required')
        unlink, link = module.os.unlink, module.os.link
        retained = []
        def fuse_unlink(name, *, dir_fd=None):
            if name.startswith('.restore-staging-'):
                staged = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
                # Model FUSE's retained name only when an open file description
                # still references the inode being unlinked. No ignored cleanup.
                for entry in os.listdir(descriptors):
                    try:
                        held = os.fstat(int(entry))
                    except (ValueError, OSError):
                        continue
                    if (held.st_dev, held.st_ino) == (staged.st_dev, staged.st_ino):
                        link(name, '.fuse-retained-restore', src_dir_fd=dir_fd,
                             dst_dir_fd=dir_fd, follow_symlinks=False)
                        retained.append(True)
                        break
            return unlink(name, dir_fd=dir_fd)
        with patch.object(module.os, 'unlink', fuse_unlink):
            result = self.restore()
        self.assertEqual(result['status'], 'disposable_restore_verified')
        self.assertEqual(retained, [])
        self.assertEqual(self.output.stat().st_nlink, 1)
        self.originals_intact()

    def test_completed_restore_is_not_automatically_repeated(self):
        self.restore(); self.blocked_retry()
        self.assertTrue((self.root / module.COMPLETE).exists())
        self.assertEqual(self.database.read_bytes(), self.database_bytes)


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(RestoreFixtureTests))
    if not result.wasSuccessful() or result.testsRun != 17 or result.skipped: raise SystemExit(1)
    evidence = retained_evidence()
    print(json.dumps({'retained_evidence_basename': evidence,
        'status': 'disposable_restore_rehearsal_verified', 'tests': result.testsRun,
        'fixture_only': True, 'production_restore_performed': False,
        'production_activation': 'disabled', 'production_authorized': False}))
