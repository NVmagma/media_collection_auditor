"""Regression tests for interrupted moves and grace-period reconciliation."""
import datetime
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import collection_auditor as auditor


class InterruptedMoveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.lib = {"name": "Movies", "state_prefix": "",
                    **{stage: str(root / stage) for stage in
                       ("transient", "holding", "removal", "keep")},
                    "app_holding": "/media/Movies_hold",
                    "app_removal": "/media/Movies_removal",
                    "app_keep": "/media/Movies_keep"}
        for stage in ("transient", "holding", "removal", "keep"):
            Path(self.lib[stage]).mkdir()
        self.state = {"first_seen": {}, "queued": {}, "in_removal": {},
                      "keep_seen": {}, "arr_sync_pending": {}}

    def test_interrupted_holding_to_removal_starts_new_clock(self):
        (Path(self.lib["removal"]) / "Film").mkdir()
        self.state["queued"]["Film"] = "2025-01-01T00:00:00"
        with patch.object(auditor, "DRY_RUN", False):
            before = datetime.datetime.now()
            auditor.reconcile_moved_titles(self.lib, self.state)
            auditor.audit_removal(self.lib, self.state, {"Film": None})
            after = datetime.datetime.now()
        self.assertNotIn("Film", self.state["queued"])
        entered = datetime.datetime.fromisoformat(self.state["in_removal"]["Film"])
        self.assertLessEqual(before, entered)
        self.assertLessEqual(entered, after)
        self.assertEqual(self.state["arr_sync_pending"]["Film"]["stage"], "removal")

    def test_stale_destination_removal_clock_is_reset(self):
        (Path(self.lib["removal"]) / "Film").mkdir()
        self.state["queued"]["Film"] = "2025-01-01T00:00:00"
        self.state["in_removal"]["Film"] = "2025-01-02T00:00:00"
        with patch.object(auditor, "DRY_RUN", False):
            before = datetime.datetime.now()
            auditor.reconcile_moved_titles(self.lib, self.state)
            after = datetime.datetime.now()
        entered = datetime.datetime.fromisoformat(self.state["in_removal"]["Film"])
        self.assertLessEqual(before, entered)
        self.assertLessEqual(entered, after)

    def test_ambiguous_move_does_not_change_clocks(self):
        (Path(self.lib["holding"]) / "Film").mkdir()
        (Path(self.lib["removal"]) / "Film").mkdir()
        self.state["queued"]["Film"] = "2025-01-01T00:00:00"
        original = dict(self.state["queued"])
        with patch.object(auditor, "DRY_RUN", False):
            auditor.reconcile_moved_titles(self.lib, self.state)
        self.assertEqual(self.state["queued"], original)
        self.assertNotIn("Film", self.state["in_removal"])
        self.assertEqual(self.state["arr_sync_pending"], {})

    def test_dry_run_does_not_rewrite_stale_timestamps(self):
        (Path(self.lib["removal"]) / "Film").mkdir()
        self.state["queued"]["Film"] = "2025-01-01T00:00:00"
        self.state["in_removal"]["Film"] = "2025-01-02T00:00:00"
        with patch.object(auditor, "DRY_RUN", True):
            auditor.reconcile_moved_titles(self.lib, self.state)
        self.assertEqual(self.state["queued"]["Film"], "2025-01-01T00:00:00")
        self.assertEqual(self.state["in_removal"]["Film"], "2025-01-02T00:00:00")
        self.assertEqual(self.state["arr_sync_pending"], {})


    def test_multiple_stale_stage_records_cannot_age_removal(self):
        (Path(self.lib["removal"]) / "Film").mkdir()
        self.state["first_seen"]["Film"] = "2024-01-01T00:00:00"
        self.state["queued"]["Film"] = "2025-01-01T00:00:00"
        self.state["in_removal"]["Film"] = "2025-02-01T00:00:00"
        with patch.object(auditor, "DRY_RUN", False):
            before = datetime.datetime.now()
            auditor.reconcile_moved_titles(self.lib, self.state)
            after = datetime.datetime.now()
        self.assertNotIn("Film", self.state["first_seen"])
        self.assertNotIn("Film", self.state["queued"])
        entered = datetime.datetime.fromisoformat(self.state["in_removal"]["Film"])
        self.assertLessEqual(before, entered)
        self.assertLessEqual(entered, after)
        self.assertEqual(self.state["arr_sync_pending"]["Film"]["stage"], "removal")

    def test_multiple_stale_stage_records_dry_run_is_read_only(self):
        (Path(self.lib["removal"]) / "Film").mkdir()
        self.state["first_seen"]["Film"] = "2024-01-01T00:00:00"
        self.state["queued"]["Film"] = "2025-01-01T00:00:00"
        self.state["in_removal"]["Film"] = "2025-02-01T00:00:00"
        original = {section: dict(entries) for section, entries in self.state.items()}
        with patch.object(auditor, "DRY_RUN", True):
            auditor.reconcile_moved_titles(self.lib, self.state)
        self.assertEqual(self.state, original)

if __name__ == "__main__":
    unittest.main()
