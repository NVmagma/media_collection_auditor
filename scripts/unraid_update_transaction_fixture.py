"""Durable handoff/recovery faults on a synthetic fixture engine; no Docker."""
from copy import deepcopy
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from scripts.sqlite_preview_cutover_fixture import PreviewCutoverFixtureTests, IDENTIFIER, NEW
from scripts.sqlite_preview_service_fixture import Engine, NEW_ID
from scripts.sqlite_preview_service import preview_payload
from scripts.unraid_update_transaction import apply_fixture_update, recover_fixture_update, UpdateJournal, read_update


class UpdateTransactionTests(unittest.TestCase):
    def setUp(self):
        self.case = PreviewCutoverFixtureTests(); self.case.setUp(); self.addCleanup(self.case.doCleanups)
        _, _, self.env, _ = self.case.render()
        self.original = deepcopy(self.case.old[0]); self.original['Name'] = '/auditor-update-fixture-test'
        self.engine = Engine(self.original); self.engine.assert_fixture = lambda: None
        self.attempt = '3'*64
        image = self.engine.selected_image
        self.payload = preview_payload(captured=self.original, image=image, env=self.env,
            control_host='/private-fixture/new-control', reference=NEW, request_id=self.attempt)
        self.parent = os.open(self.case.root, os.O_RDONLY | os.O_DIRECTORY); self.addCleanup(os.close, self.parent)
        self.invalid = False; self.templates = []

    def data(self):
        if self.invalid: raise RuntimeError('fixture data diverged')

    def apply(self, **changes):
        options = dict(engine=self.engine, journal=UpdateJournal(self.parent), captured=self.original,
            payload=self.payload, image_id=NEW, attempt=self.attempt, validate_data=self.data,
            health=lambda item: None, install_template=lambda: self.templates.append('new'))
        options.update(changes); return apply_fixture_update(**options)

    def recover(self, **changes):
        options = dict(engine=self.engine, journal=UpdateJournal(self.parent, 'recovery'), parent=self.parent,
            captured=self.original, payload=self.payload, image_id=NEW, attempt=self.attempt,
            validate_data=self.data, restore_template=lambda: self.templates.append('old'), health=lambda item: None)
        options.update(changes); return recover_fixture_update(**options)

    def test_success_and_explicit_recovery_retain_both_containers(self):
        result = self.apply(); self.assertEqual(result['status'], 'fixture_update_complete')
        self.assertFalse(self.engine.inspect(IDENTIFIER)['State']['Running'])
        self.assertTrue(self.engine.inspect(NEW_ID)['State']['Running'])
        self.assertEqual(read_update(self.parent)[1][-1], 'update_complete')
        self.assertFalse(result['automatic_restoration'])
        self.assertEqual(self.recover()['status'], 'fixture_original_recovered')
        self.assertTrue(self.engine.inspect(IDENTIFIER)['State']['Running'])
        self.assertFalse(self.engine.inspect(NEW_ID)['State']['Running'])
        self.assertEqual(len(self.engine.containers), 2); self.assertEqual(self.templates, ['new','old'])

    def test_lost_stop_ack_leaves_original_stopped_until_explicit_recovery(self):
        self.engine.lose_ack = 'stop'
        with self.assertRaises(TimeoutError): self.apply()
        self.assertFalse(self.engine.inspect(IDENTIFIER)['State']['Running'])
        self.assertEqual(read_update(self.parent)[1], ['old_stop_requested'])
        self.assertEqual(self.engine.calls, [('stop', IDENTIFIER)])
        self.engine.lose_ack = None
        self.recover(); self.assertTrue(self.engine.inspect(IDENTIFIER)['State']['Running'])

    def test_lost_create_ack_requires_explicit_identity_and_never_recreates(self):
        self.engine.lose_ack = 'create'
        with self.assertRaises(TimeoutError): self.apply()
        before = list(self.engine.calls)
        with self.assertRaises(RuntimeError): self.recover()
        self.assertEqual(self.engine.calls, before)
        self.engine.lose_ack = None
        self.recover(reviewed_new_id=NEW_ID)
        self.assertEqual(sum(call[0]=='create' for call in self.engine.calls), 1)

    def test_failed_health_never_installs_template_or_automatically_recovers(self):
        def fail(item): raise RuntimeError('fixture unhealthy')
        with self.assertRaises(RuntimeError): self.apply(health=fail)
        self.assertFalse(self.engine.inspect(IDENTIFIER)['State']['Running'])
        self.assertEqual(self.templates, [])
        self.recover(); self.assertEqual(self.templates, ['old'])

    def test_diverged_data_blocks_recovery_without_any_service_effect(self):
        self.apply(); self.invalid = True
        before = list(self.engine.calls)
        with self.assertRaises(RuntimeError): self.recover()
        self.assertEqual(self.engine.calls, before)
        self.assertFalse(self.engine.inspect(IDENTIFIER)['State']['Running'])

    def test_changed_journal_and_payload_cannot_authorize_recovery(self):
        self.apply(); before = list(self.engine.calls)
        changed = deepcopy(self.payload); changed['Env'].append('CHANGED=true')
        with self.assertRaises(RuntimeError): self.recover(payload=changed)
        path = self.case.root/'update-0001.json'; path.write_bytes(b'{}')
        with self.assertRaises(RuntimeError): self.recover()
        self.assertEqual(self.engine.calls, before)

    def test_apply_and_recovery_cannot_replay_completed_attempts(self):
        self.apply(); before = list(self.engine.calls)
        with self.assertRaises(RuntimeError): self.apply()
        self.assertEqual(self.engine.calls, before)
        self.recover(); before = list(self.engine.calls)
        with self.assertRaises(RuntimeError): self.recover()
        self.assertEqual(self.engine.calls, before)

    def test_production_service_name_is_refused_before_journal_or_stop(self):
        self.original['Name'] = '/media_collection_auditor'
        with self.assertRaises(ValueError): self.apply()
        self.assertEqual(self.engine.calls, [])
        self.assertFalse((self.case.root/'update-request.json').exists())


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(UpdateTransactionTests))
    raise SystemExit(0 if result.wasSuccessful() else 1)
