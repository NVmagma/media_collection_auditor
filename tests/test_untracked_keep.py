"""Safety tests for observing untracked Keep media without changing files."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import collection_auditor as auditor


class KeepObservationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.lib = {"name": "Movies", "state_prefix": "", **{
            stage: str(root / stage) for stage in ("keep", "transient", "holding", "removal")}}
        for stage in ("keep", "transient", "holding", "removal"):
            (root / stage).mkdir()
        (root / "keep" / "Film").mkdir()
        self.state = {key: {} for key in ("first_seen", "queued", "in_removal", "keep_seen")}

    def test_untracked_keep_observed_without_media_move(self):
        with patch.object(auditor, "DRY_RUN", False):
            auditor.reconcile_untracked_keep(self.lib, self.state)
        self.assertIn("Film", self.state["keep_seen"])
        self.assertTrue((Path(self.lib["keep"]) / "Film").is_dir())

    def test_dry_run_never_changes_state(self):
        with patch.object(auditor, "DRY_RUN", True):
            auditor.reconcile_untracked_keep(self.lib, self.state)
        self.assertEqual(self.state["keep_seen"], {})

    def test_ambiguous_folder_is_not_recorded(self):
        (Path(self.lib["transient"]) / "Film").mkdir()
        with patch.object(auditor, "DRY_RUN", False):
            auditor.reconcile_untracked_keep(self.lib, self.state)
        self.assertEqual(self.state["keep_seen"], {})

    def test_existing_stage_history_is_preserved(self):
        self.state["first_seen"]["Film"] = "2026-01-01"
        with patch.object(auditor, "DRY_RUN", False):
            auditor.reconcile_untracked_keep(self.lib, self.state)
        self.assertEqual(self.state["first_seen"]["Film"], "2026-01-01")
        self.assertEqual(self.state["keep_seen"], {})


if __name__ == "__main__":
    unittest.main()
