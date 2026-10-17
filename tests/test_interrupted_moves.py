"""Interrupted-move recovery tests using disposable directories only."""
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import collection_auditor as auditor


class InterruptedMoveRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.waiting = root / "waiting"
        self.holding = root / "holding"
        self.removal = root / "removal"
        self.keep = root / "keep"
        for folder in (self.waiting, self.holding, self.removal, self.keep):
            folder.mkdir()
        self.lib = {
            "name": "Movies", "state_prefix": "",
            "transient": str(self.waiting), "holding": str(self.holding),
            "removal": str(self.removal), "keep": str(self.keep),
            "app_holding": str(self.holding), "app_removal": str(self.removal),
            "app_keep": str(self.keep),
            "wait_days": 30, "new_content_resets_clock": False,
        }
        self.state = {"first_seen": {}, "queued": {}, "in_removal": {}, "keep_seen": {}}

    def test_interrupted_waiting_to_keep_does_not_repeat_move(self):
        # Simulate a completed move with old, unsaved Waiting state.
        (self.keep / "Example").mkdir()
        self.state["first_seen"]["Example"] = "2026-01-01T00:00:00"
        with patch.object(auditor, "move_or_report") as move:
            auditor.audit_transient(self.lib, {"Example": {
                "played": False, "favorite": True, "disliked": False,
                "keep": True, "protected": False,
            }}, self.state)
        move.assert_not_called()
        self.assertNotIn("Example", self.state["first_seen"])
        self.assertTrue((self.keep / "Example").is_dir())

    def test_interrupted_holding_entry_starts_new_grace_period(self):
        (self.holding / "Example").mkdir()
        self.state["first_seen"]["Example"] = "2020-01-01T00:00:00"
        with patch.object(auditor, "DRY_RUN", False), \
             patch.object(auditor, "move_or_report") as move:
            auditor.audit_holding(self.lib, {"Example": {}}, self.state)
        move.assert_not_called()
        self.assertIn("Example", self.state["queued"])
        entered = datetime.fromisoformat(self.state["queued"]["Example"])
        self.assertLess((datetime.now() - entered).total_seconds(), 60)

    def test_interrupted_removal_entry_starts_new_grace_period(self):
        (self.removal / "Example").mkdir()
        with patch.object(auditor, "DRY_RUN", False), \
             patch.object(auditor, "remove_media") as delete:
            auditor.audit_removal(self.lib, self.state, {"Example": {}})
        delete.assert_not_called()
        self.assertIn("Example", self.state["in_removal"])
        entered = datetime.fromisoformat(self.state["in_removal"]["Example"])
        self.assertLess((datetime.now() - entered).total_seconds(), 60)

    def test_reconcile_interrupted_move_to_keep(self):
        (self.keep / "Example").mkdir()
        self.state["queued"]["Example"] = "2026-01-01T00:00:00"
        with patch.object(auditor, "DRY_RUN", False):
            auditor.reconcile_moved_titles(self.lib, self.state)
        self.assertNotIn("Example", self.state["queued"])
        self.assertIn("Example", self.state["keep_seen"])
        self.assertEqual(self.state["arr_sync_pending"]["Example"]["stage"], "keep")
        self.assertTrue((self.keep / "Example").is_dir())

    def test_reconcile_does_not_inherit_holding_age_in_removal(self):
        (self.removal / "Example").mkdir()
        self.state["queued"]["Example"] = "2020-01-01T00:00:00"
        with patch.object(auditor, "DRY_RUN", False), \
             patch.object(auditor, "remove_media") as delete:
            auditor.reconcile_moved_titles(self.lib, self.state)
            auditor.audit_removal(self.lib, self.state, {"Example": {}})
        self.assertNotIn("Example", self.state["queued"])
        self.assertIn("Example", self.state["in_removal"])
        delete.assert_not_called()
        self.assertEqual(self.state["arr_sync_pending"]["Example"]["stage"], "removal")

    def test_conflicting_removal_clock_is_reset_before_deletion(self):
        (self.removal / "Example").mkdir()
        self.state["queued"]["Example"] = "2020-01-01T00:00:00"
        self.state["in_removal"]["Example"] = "2020-01-01T00:00:00"
        with (patch.object(auditor, "DRY_RUN", False),
              patch.object(auditor, "remove_media") as delete):
            auditor.reconcile_moved_titles(self.lib, self.state)
            auditor.audit_removal(self.lib, self.state, {"Example": {}})
        delete.assert_not_called()
        self.assertNotIn("Example", self.state["queued"])
        entered = datetime.fromisoformat(self.state["in_removal"]["Example"])
        self.assertLess((datetime.now() - entered).total_seconds(), 60)

    def test_conflicting_holding_clock_is_reset(self):
        (self.holding / "Example").mkdir()
        self.state["first_seen"]["Example"] = "2020-01-01T00:00:00"
        self.state["queued"]["Example"] = "2020-01-01T00:00:00"
        with patch.object(auditor, "DRY_RUN", False):
            auditor.reconcile_moved_titles(self.lib, self.state)
        self.assertNotIn("Example", self.state["first_seen"])
        entered = datetime.fromisoformat(self.state["queued"]["Example"])
        self.assertLess((datetime.now() - entered).total_seconds(), 60)

    def test_reconcile_leaves_ambiguous_locations_untouched(self):
        (self.holding / "Example").mkdir()
        (self.keep / "Example").mkdir()
        self.state["first_seen"]["Example"] = "2026-01-01T00:00:00"
        with patch.object(auditor, "DRY_RUN", False):
            auditor.reconcile_moved_titles(self.lib, self.state)
        self.assertIn("Example", self.state["first_seen"])
        self.assertNotIn("Example", self.state["keep_seen"])
        self.assertNotIn("Example", self.state.get("arr_sync_pending", {}))

    def test_reconcile_dry_run_does_not_mutate_state(self):
        (self.keep / "Example").mkdir()
        self.state["queued"]["Example"] = "2026-01-01T00:00:00"
        with patch.object(auditor, "DRY_RUN", True):
            auditor.reconcile_moved_titles(self.lib, self.state)
        self.assertIn("Example", self.state["queued"])
        self.assertNotIn("Example", self.state["keep_seen"])
        self.assertNotIn("Example", self.state.get("arr_sync_pending", {}))

    def test_unknown_jellyfin_signals_block_removal(self):
        (self.removal / "Example").mkdir()
        self.state["in_removal"]["Example"] = "2020-01-01T00:00:00"
        with patch.object(auditor, "remove_media") as delete:
            auditor.audit_removal(self.lib, self.state, {})
        delete.assert_not_called()
        self.assertTrue((self.removal / "Example").is_dir())


if __name__ == "__main__":
    unittest.main()
