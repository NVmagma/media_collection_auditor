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

    def test_restart_preserves_all_lifecycle_timestamps(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = os.path.join(directory, "state.json")
            original = {
                "first_seen": {"Waiting Film": "2025-01-02T03:04:05"},
                "queued": {"Holding Film": "2025-02-03T04:05:06"},
                "in_removal": {"Removal Film": "2025-03-04T05:06:07"},
                "keep_seen": {"Keep Film": "2025-04-05T06:07:08"},
                "arr_sync_pending": {
                    "Holding Film": {"stage": "holding", "root": "/media/Movies_hold",
                                     "monitored": False},
                },
            }
            with patch.object(auditor, "STATE_FILE", state_path):
                auditor.save_state(original)
                first_load = auditor.load_state()
                self.assertEqual(first_load, original)
                auditor.save_state(first_load)
                restarted = auditor.load_state()
            self.assertEqual(restarted, original)

    def test_corrupted_existing_state_cannot_be_overwritten_by_recovery_load(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = os.path.join(directory, "state.json")
            original = {"first_seen": {"Film": "2025-01-01T00:00:00"},
                        "queued": {}, "in_removal": {}, "keep_seen": {},
                        "arr_sync_pending": {}}
            with patch.object(auditor, "STATE_FILE", state_path):
                auditor.save_state(original)
                with open(state_path, "w") as handle:
                    handle.write('{"first_seen":')
                with self.assertRaisesRegex(RuntimeError, "refusing to reset tracking history"):
                    auditor.load_state()
            with open(state_path) as handle:
                self.assertEqual(handle.read(), '{"first_seen":')

    def test_abandoned_temporary_file_does_not_override_valid_state(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = os.path.join(directory, "state.json")
            original = {"first_seen": {"Film": "2025-01-01T00:00:00"},
                        "queued": {}, "in_removal": {}, "keep_seen": {},
                        "arr_sync_pending": {}}
            with patch.object(auditor, "STATE_FILE", state_path):
                auditor.save_state(original)
                with open(os.path.join(directory, ".auditor_state_interrupted.tmp"), "w") as handle:
                    handle.write('{"queued":')
                self.assertEqual(auditor.load_state(), original)
            with open(state_path) as handle:
                self.assertIn("2025-01-01T00:00:00", handle.read())

    def test_missing_state_with_abandoned_write_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            state_path = os.path.join(directory, "state.json")
            with open(os.path.join(directory, ".auditor_state_interrupted.tmp"), "w") as handle:
                handle.write('{"first_seen":')
            with patch.object(auditor, "STATE_FILE", state_path):
                with self.assertRaisesRegex(RuntimeError, "refusing to reset tracking history"):
                    auditor.load_state()
            self.assertFalse(os.path.exists(state_path))

    def test_state_directory_sync_failure_is_reported_without_erasing_state(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "state.json")
            state = {"first_seen": {"Film": "2025-01-01T00:00:00"},
                     "queued": {}, "in_removal": {}, "keep_seen": {},
                     "arr_sync_pending": {}}
            with patch.object(auditor, "STATE_FILE", path):
                auditor.save_state(state)
                real_fsync = auditor.os.fsync
                calls = []
                def fail_directory_sync(fd):
                    calls.append(fd)
                    if len(calls) == 2:
                        raise OSError("directory sync failed")
                    return real_fsync(fd)
                with patch.object(auditor.os, "fsync", side_effect=fail_directory_sync):
                    with self.assertRaisesRegex(RuntimeError, "Failed to persist auditor state"):
                        auditor.save_state(state)
                self.assertEqual(auditor.load_state(), state)
            self.assertEqual(sorted(os.listdir(directory)), ["state.json"])

if __name__ == "__main__":
    unittest.main()
