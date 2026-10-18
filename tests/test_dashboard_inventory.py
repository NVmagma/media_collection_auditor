"""Read-only dashboard filesystem inventory tests."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import web


class DashboardInventoryTests(unittest.TestCase):
    def test_real_directories_determine_stage_counts(self):
        with tempfile.TemporaryDirectory() as root:
            for folder in ("Movies", "Movies_hold", "Movies_keep", "Movies_removal"):
                os.mkdir(os.path.join(root, folder))
            os.mkdir(os.path.join(root, "Movies_keep", "Kept"))
            os.mkdir(os.path.join(root, "Movies", "New"))
            state = {"first_seen": {"Stale": "2020-01-01T00:00:00"},
                     "keep_seen": {"Kept": "2026-01-01T00:00:00"}}
            with patch.dict(os.environ, {"MEDIA_PATH": root}, clear=False):
                stages, warnings = web.filesystem_stages(state, {
                    "MEDIA_PATH": root, "ENABLE_MOVIES": "true", "ENABLE_TV": "false"})
        self.assertFalse(warnings)
        self.assertEqual([item["title"] for item in stages["Waiting"]], ["New"])
        self.assertEqual([item["title"] for item in stages["Keep"]], ["Kept"])
        self.assertIsNone(stages["Waiting"][0]["since"])

    def test_collection_health_reports_missing_stale_and_pending(self):
        state = {"first_seen": {"Stale": "2020-01-01T00:00:00"},
                 "arr_sync_pending": {"Kept": {"stage": "keep", "root": "/media/Movies_keep"}}}
        stages = {"Waiting": [{"library": "Movies", "title": "New", "since": None}],
                  "Holding": [], "Removal": [], "Keep": []}
        issues = web.collection_health(state, stages, [])
        details = [item["detail"] for item in issues]
        self.assertTrue(any("no tracking timestamp" in detail for detail in details))
        self.assertTrue(any("no matching folder" in detail for detail in details))
        self.assertTrue(any("sync pending" in detail for detail in details))

    def test_collection_health_does_not_claim_missing_media_when_mount_unavailable(self):
        state = {"in_removal": {"Important": "2020-01-01T00:00:00"}}
        stages = {"Waiting": [], "Holding": [], "Removal": [], "Keep": []}
        issues = web.collection_health(state, stages, ["Movies Removal: directory unavailable (/media/Movies_removal)"])
        self.assertEqual(issues, [])

    def test_unavailable_mount_reports_warning(self):
        with tempfile.TemporaryDirectory() as root:
            stages, warnings = web.filesystem_stages({}, {
                "MEDIA_PATH": root, "ENABLE_MOVIES": "true", "ENABLE_TV": "false"})
        self.assertEqual(sum(map(len, stages.values())), 0)
        self.assertEqual(len(warnings), 4)


if __name__ == "__main__":
    unittest.main()
