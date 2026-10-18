"""Radarr/Sonarr synchronization failure tests; no external services required."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import collection_auditor as auditor


class ArrSyncFailureTests(unittest.TestCase):
    def test_failed_sync_is_recorded_without_undoing_move(self):
        arr = SimpleNamespace(name="Radarr", notify_moved=lambda *args: False)
        lib = {"name": "Movies", "arr": arr}
        with patch.object(auditor, "record_action") as record:
            auditor.sync_arr(lib, "Example", "/movies/keep", monitored=True)
        record.assert_called_once_with(
            "arr_sync_failed", "Example",
            "Radarr was NOT updated after the move; retry pending if tracked",
            "Movies", status="failed",
        )

    def test_failed_sync_queues_retry_and_success_clears_it(self):
        with __import__("tempfile").TemporaryDirectory() as directory:
            from pathlib import Path
            keep = Path(directory) / "keep"
            keep.mkdir()
            (keep / "Example").mkdir()
            calls = []
            results = iter([False, True])
            arr = SimpleNamespace(name="Radarr",
                                  notify_moved=lambda *args: calls.append(args) or next(results))
            lib = {"name": "Movies", "state_prefix": "", "arr": arr,
                   "keep": str(keep), "holding": str(Path(directory) / "holding"),
                   "removal": str(Path(directory) / "removal"),
                   "transient": str(Path(directory) / "waiting"),
                   "app_keep": "/arr/keep"}
            state = {"arr_sync_pending": {}}
            with patch.object(auditor, "DRY_RUN", False), \
                 patch.object(auditor, "record_action"):
                auditor.sync_arr(lib, "Example", "/arr/keep", state=state, stage="keep")
                self.assertIn("Example", state["arr_sync_pending"])
                auditor.retry_pending_arr_sync(lib, state)
            self.assertNotIn("Example", state["arr_sync_pending"])
            self.assertEqual(len(calls), 2)

    def test_retry_skips_missing_media(self):
        arr = SimpleNamespace(name="Radarr",
                              notify_moved=lambda *args: self.fail("Must not sync absent media"))
        with __import__("tempfile").TemporaryDirectory() as directory:
            lib = {"name": "Movies", "state_prefix": "", "arr": arr,
                   **{kind: str(Path(directory) / kind)
                      for kind in ("transient", "holding", "removal", "keep")},
                   "app_keep": "/arr/keep"}
            state = {"arr_sync_pending": {"Example": {
                "stage": "keep", "root": "/arr/keep", "monitored": True}}}
            with (patch.object(auditor, "DRY_RUN", False),
                  patch.object(auditor, "record_action")):
                auditor.retry_pending_arr_sync(lib, state)
            self.assertIn("Example", state["arr_sync_pending"])

    def test_successful_sync_does_not_log_failure(self):
        calls = []
        arr = SimpleNamespace(
            name="Sonarr",
            notify_moved=lambda *args: calls.append(args) or True,
        )
        lib = {"name": "TV", "arr": arr}
        with patch.object(auditor, "record_action") as record:
            auditor.sync_arr(lib, "Example", "/tv/keep", monitored=True)
        self.assertEqual(calls, [("Example", "/tv/keep", True)])
        record.assert_not_called()


if __name__ == "__main__":
    unittest.main()
