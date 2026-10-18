"""Ensure duplicate lifecycle folders never authorize Removal deletion."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import collection_auditor as auditor


class DuplicateRemovalSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.lib = {"name": "Movies", "state_prefix": "",
                    **{stage: str(root / stage) for stage in
                       ("transient", "holding", "removal", "keep")}}
        for stage in ("transient", "holding", "removal", "keep"):
            Path(self.lib[stage]).mkdir()
        (Path(self.lib["removal"]) / "Film").mkdir()
        self.state = {"first_seen": {}, "queued": {},
                      "in_removal": {"Film": "2020-01-01T00:00:00"},
                      "keep_seen": {}, "arr_sync_pending": {}}

    def test_duplicate_in_any_other_stage_blocks_removal(self):
        for stage in ("transient", "holding", "keep"):
            with self.subTest(stage=stage):
                duplicate = Path(self.lib[stage]) / "Film"
                duplicate.mkdir()
                with patch.object(auditor, "DRY_RUN", False), \
                     patch.object(auditor, "action_allowed", return_value=True) as allowed, \
                     patch.object(auditor, "remove_media") as remove:
                    auditor.audit_removal(self.lib, self.state, {"Film": {}})
                allowed.assert_not_called()
                remove.assert_not_called()
                self.assertEqual(self.state["in_removal"]["Film"], "2020-01-01T00:00:00")
                duplicate.rmdir()

    def test_missing_jellyfin_signals_still_blocks_removal(self):
        with patch.object(auditor, "DRY_RUN", False), \
             patch.object(auditor, "action_allowed", return_value=True) as allowed, \
             patch.object(auditor, "remove_media") as remove:
            auditor.audit_removal(self.lib, self.state, {"Film": None})
        allowed.assert_not_called()
        remove.assert_not_called()


if __name__ == "__main__":
    unittest.main()
