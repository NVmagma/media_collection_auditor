"""Verify stage clocks and safe state transitions using disposable folders."""
import datetime
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import collection_auditor as auditor


class StageTransitionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.lib = {"name": "Movies", "state_prefix": "",
                    "holding": str(root / "holding"),
                    "app_holding": "/media/Movies_hold",
                    "removal": str(root / "removal"),
                    "app_removal": "/media/Movies_removal",
                    "transient": str(root / "transient")}
        for path in (self.lib["holding"], self.lib["transient"], self.lib["removal"]):
            Path(path).mkdir()
        (Path(self.lib["transient"]) / "Film").mkdir()
        self.state = {"first_seen": {"Film": "2025-01-01T00:00:00"},
                      "queued": {}, "in_removal": {}, "keep_seen": {}}

    def test_successful_holding_move_starts_new_clock_and_clears_waiting(self):
        with patch.object(auditor, "DRY_RUN", False), \
             patch.object(auditor, "action_allowed", return_value=True), \
             patch.object(auditor, "move_or_report", return_value=True), \
             patch.object(auditor, "action_done"), \
             patch.object(auditor, "record_action"), \
             patch.object(auditor, "sync_arr"):
            before = datetime.datetime.now()
            auditor.move_to_holding(self.lib, "Film", self.lib["transient"],
                                    self.state, "expired")
            after = datetime.datetime.now()
        self.assertNotIn("Film", self.state["first_seen"])
        entered = datetime.datetime.fromisoformat(self.state["queued"]["Film"])
        self.assertLessEqual(before, entered)
        self.assertLessEqual(entered, after)

    def test_failed_move_preserves_original_tracking(self):
        with patch.object(auditor, "DRY_RUN", False), \
             patch.object(auditor, "action_allowed", return_value=True), \
             patch.object(auditor, "move_or_report", return_value=False):
            auditor.move_to_holding(self.lib, "Film", self.lib["transient"],
                                    self.state, "expired")
        self.assertEqual(self.state["first_seen"]["Film"], "2025-01-01T00:00:00")
        self.assertEqual(self.state["queued"], {})

    def test_dry_run_preserves_original_tracking(self):
        with patch.object(auditor, "DRY_RUN", True), \
             patch.object(auditor, "action_allowed", return_value=True), \
             patch.object(auditor, "move_or_report", return_value=True), \
             patch.object(auditor, "action_done"), \
             patch.object(auditor, "record_action"), \
             patch.object(auditor, "sync_arr"):
            auditor.move_to_holding(self.lib, "Film", self.lib["transient"],
                                    self.state, "expired")
        self.assertEqual(self.state["first_seen"]["Film"], "2025-01-01T00:00:00")
        self.assertEqual(self.state["queued"], {})


    def test_holding_to_removal_starts_fresh_clock(self):
        (Path(self.lib["holding"]) / "Film").mkdir()
        self.state["first_seen"].clear()
        self.state["queued"]["Film"] = "2025-01-01T00:00:00"
        with patch.object(auditor, "DRY_RUN", False), \
             patch.object(auditor, "decide", return_value=("to_removal", "expired")), \
             patch.object(auditor, "move_or_report", return_value=True), \
             patch.object(auditor, "record_action"), \
             patch.object(auditor, "sync_arr"):
            before = datetime.datetime.now()
            auditor.audit_holding(self.lib, {"Film": {}}, self.state)
            after = datetime.datetime.now()
        self.assertNotIn("Film", self.state["queued"])
        entered = datetime.datetime.fromisoformat(self.state["in_removal"]["Film"])
        self.assertLessEqual(before, entered)
        self.assertLessEqual(entered, after)

    def test_failed_holding_to_removal_preserves_clock(self):
        (Path(self.lib["holding"]) / "Film").mkdir()
        self.state["first_seen"].clear()
        self.state["queued"]["Film"] = "2025-01-01T00:00:00"
        with patch.object(auditor, "DRY_RUN", False), \
             patch.object(auditor, "decide", return_value=("to_removal", "expired")), \
             patch.object(auditor, "move_or_report", return_value=False):
            auditor.audit_holding(self.lib, {"Film": {}}, self.state)
        self.assertEqual(self.state["queued"]["Film"], "2025-01-01T00:00:00")
        self.assertNotIn("Film", self.state["in_removal"])

    def test_dry_run_holding_to_removal_preserves_clock(self):
        (Path(self.lib["holding"]) / "Film").mkdir()
        self.state["first_seen"].clear()
        self.state["queued"]["Film"] = "2025-01-01T00:00:00"
        with patch.object(auditor, "DRY_RUN", True), \
             patch.object(auditor, "decide", return_value=("to_removal", "expired")), \
             patch.object(auditor, "move_or_report", return_value=True), \
             patch.object(auditor, "record_action"), \
             patch.object(auditor, "sync_arr"):
            auditor.audit_holding(self.lib, {"Film": {}}, self.state)
        self.assertEqual(self.state["queued"]["Film"], "2025-01-01T00:00:00")
        self.assertNotIn("Film", self.state["in_removal"])

    def test_missing_jellyfin_signals_cannot_advance_holding(self):
        (Path(self.lib["holding"]) / "Film").mkdir()
        self.state["queued"]["Film"] = "2025-01-01T00:00:00"
        with patch.object(auditor, "DRY_RUN", False), \\
             patch.object(auditor, "move_or_report") as move:
            auditor.audit_holding(self.lib, {}, self.state)
        move.assert_not_called()
        self.assertEqual(self.state["queued"]["Film"], "2025-01-01T00:00:00")
        self.assertEqual(self.state["in_removal"], {})

    def test_protected_holding_title_cannot_advance_to_removal(self):
        (Path(self.lib["holding"]) / "Film").mkdir()
        self.state["queued"]["Film"] = "2025-01-01T00:00:00"
        with patch.object(auditor, "DRY_RUN", False), \\
             patch.object(auditor, "move_or_report", return_value=False) as move:
            auditor.audit_holding(self.lib, {"Film": {"protected": True}}, self.state)
        move.assert_called_once()
        self.assertEqual(move.call_args.args[3], self.lib["keep"])
        self.assertEqual(self.state["queued"]["Film"], "2025-01-01T00:00:00")
        self.assertEqual(self.state["in_removal"], {})

if __name__ == "__main__":
    unittest.main()
