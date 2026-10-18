"""Read-only collection health discrepancy tests."""
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("WEB_SESSION_SECRET", "test-only-not-for-production")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from web import collection_health


class CollectionHealthTests(unittest.TestCase):
    def test_duplicate_folder_and_cross_stage_record(self):
        stages = {"Waiting": [{"library": "Movies", "title": "Film", "since": "2026-10-01"}],
                  "Holding": [{"library": "Movies", "title": "Film", "since": None}],
                  "Removal": [], "Keep": []}
        state = {"first_seen": {}, "queued": {}, "in_removal": {"Film": "2026-10-01"},
                 "keep_seen": {}}
        details = [x["detail"] for x in collection_health(state, stages, [])]
        self.assertTrue(any("multiple lifecycle directories" in d for d in details))
        self.assertTrue(any("no tracking timestamp" in d for d in details))
        self.assertTrue(any("Removal tracking record, but folder is in" in d for d in details))

    def test_unavailable_directory_does_not_imply_missing_media(self):
        stages = {"Waiting": [], "Holding": [], "Removal": [], "Keep": []}
        state = {"first_seen": {"Film": "2026-10-01"}, "queued": {},
                 "in_removal": {}, "keep_seen": {}}
        self.assertEqual(collection_health(state, stages,
                         ["Movies Waiting: directory unavailable (/media/Movies)"]), [])

    def test_missing_folder_reported_with_complete_inventory(self):
        stages = {"Waiting": [], "Holding": [], "Removal": [], "Keep": []}
        state = {"first_seen": {"Film": "2026-10-01"}, "queued": {},
                 "in_removal": {}, "keep_seen": {}}
        self.assertIn("no matching folder", collection_health(state, stages, [])[0]["detail"])


if __name__ == "__main__":
    unittest.main()
