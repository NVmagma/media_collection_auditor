"""Regression tests for tracking-state persistence failures."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import collection_auditor as auditor


class StatePersistenceTests(unittest.TestCase):
    def test_save_state_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = os.path.join(directory, "state.json")
            state = {"first_seen": {"Example": "2026-01-01"}, "queued": {},
                     "in_removal": {}, "keep_seen": {}, "arr_sync_pending": {}}
            with patch.object(auditor, "STATE_FILE", state_path):
                auditor.save_state(state)
                self.assertEqual(auditor.load_state(), state)

    def test_missing_state_file_starts_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(auditor, "STATE_FILE", os.path.join(directory, "missing.json")):
                state = auditor.load_state()
        self.assertEqual(state["arr_sync_pending"], {})
        self.assertEqual(state["first_seen"], {})

    def test_corrupt_json_does_not_reset_tracking(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "state.json")
            with open(path, "w") as f:
                f.write('{"first_seen":')
            with patch.object(auditor, "STATE_FILE", path):
                with self.assertRaisesRegex(RuntimeError, "refusing to reset tracking history"):
                    auditor.load_state()
            with open(path) as f:
                self.assertEqual(f.read(), '{"first_seen":')

    def test_invalid_state_structure_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "state.json")
            for contents in ('[]', '{"queued": []}', 'null'):
                with self.subTest(contents=contents):
                    with open(path, "w") as f:
                        f.write(contents)
                    with patch.object(auditor, "STATE_FILE", path):
                        with self.assertRaisesRegex(RuntimeError, "refusing to reset tracking history"):
                            auditor.load_state()

    def test_invalid_lifecycle_timestamps_fail_closed(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "state.json")
            for value in ("not-a-date", "2999-01-01T00:00:00", 123, "2026-01-01T00:00:00+00:00"):
                with self.subTest(value=value):
                    with open(path, "w") as handle:
                        json.dump({"in_removal": {"Example": value}}, handle)
                    with patch.object(auditor, "STATE_FILE", path):
                        with self.assertRaises(RuntimeError):
                            auditor.load_state()

    def test_invalid_arr_retry_record_fails_closed(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "state.json")
            for entry in (None, {}, {"stage": "unknown", "root": "/arr", "monitored": False},
                          {"stage": "keep", "root": "/arr", "monitored": "yes"}):
                with self.subTest(entry=entry):
                    with open(path, "w") as handle:
                        json.dump({"arr_sync_pending": {"Example": entry}}, handle)
                    with patch.object(auditor, "STATE_FILE", path):
                        with self.assertRaises(RuntimeError):
                            auditor.load_state()

    def test_state_write_failure_is_not_silenced(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = os.path.join(directory, "state.json")
            with patch.object(auditor, "STATE_FILE", state_path), \
                 patch.object(auditor.json, "dump", side_effect=OSError("disk full")):
                with self.assertRaisesRegex(RuntimeError, "Failed to persist auditor state"):
                    auditor.save_state({"first_seen": {}, "queued": {},
                                        "in_removal": {}, "keep_seen": {}})

    def test_state_replace_failure_is_not_silenced(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = os.path.join(directory, "state.json")
            with patch.object(auditor, "STATE_FILE", state_path), \
                 patch.object(auditor.os, "replace", side_effect=OSError("read-only filesystem")):
                with self.assertRaisesRegex(RuntimeError, "Failed to persist auditor state"):
                    auditor.save_state({"first_seen": {}, "queued": {},
                                        "in_removal": {}, "keep_seen": {}})


    def test_failed_replace_keeps_previous_state_and_cleans_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = os.path.join(directory, "state.json")
            previous = {"first_seen": {"Film": "2025-01-01T00:00:00"},
                        "queued": {}, "in_removal": {}, "keep_seen": {}}
            replacement = {"first_seen": {}, "queued": {"Film": "2026-01-01T00:00:00"},
                           "in_removal": {}, "keep_seen": {}}
            with patch.object(auditor, "STATE_FILE", state_path):
                auditor.save_state(previous)
                with patch.object(auditor.os, "replace", side_effect=OSError("disk full")):
                    with self.assertRaisesRegex(RuntimeError, "Failed to persist auditor state"):
                        auditor.save_state(replacement)
                self.assertEqual(auditor.load_state()["first_seen"], previous["first_seen"])
            self.assertEqual(sorted(os.listdir(directory)), ["state.json"])

    def test_failed_serialization_keeps_previous_state_and_cleans_temporary_file(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = os.path.join(directory, "state.json")
            previous = {"first_seen": {"Film": "2025-01-01T00:00:00"},
                        "queued": {}, "in_removal": {}, "keep_seen": {}}
            with patch.object(auditor, "STATE_FILE", state_path):
                auditor.save_state(previous)
                with patch.object(auditor.json, "dump", side_effect=OSError("write failed")):
                    with self.assertRaisesRegex(RuntimeError, "Failed to persist auditor state"):
                        auditor.save_state(previous)
                self.assertEqual(auditor.load_state()["first_seen"], previous["first_seen"])
            self.assertEqual(sorted(os.listdir(directory)), ["state.json"])

if __name__ == "__main__":
    unittest.main()
