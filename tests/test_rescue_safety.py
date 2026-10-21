"""Filesystem safety tests for manual rescue. No real media is moved."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("WEB_SESSION_SECRET", "test-only-not-for-production")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import manual_rescue


class RescueSafetyTests(unittest.TestCase):
    def test_invalid_library_and_destination_rejected(self):
        for library, destination in [("Unknown", "keep"), ("Movies", "removal"), ("TV", "delete")]:
            with self.subTest(library=library, destination=destination):
                self.assertEqual(manual_rescue.rescue_title(library, "Example", destination)[2], 400)

    def test_path_traversal_rejected(self):
        for title in ("../outside", "..", ".", "/tmp/outside", "folder/subfolder"):
            with self.subTest(title=title):
                self.assertEqual(manual_rescue.rescue_title("Movies", title, "keep")[2], 400)

    def test_rescue_rejected_while_audit_busy(self):
        with patch.object(manual_rescue, "begin_rescue", return_value=False):
            self.assertEqual(manual_rescue.rescue_title("Movies", "Example", "keep")[2], 409)

    def test_dry_run_does_not_move_media(self):
        with tempfile.TemporaryDirectory() as root:
            removal = Path(root) / "removal"
            keep = Path(root) / "keep"
            removal.mkdir()
            keep.mkdir()
            (removal / "Example").mkdir()
            library = {"name": "Movies", "removal": str(removal), "keep": str(keep)}
            auditor = SimpleNamespace(
                STATE_FILE=str(Path(root) / "state.json"),
                build_libraries=lambda: [library],
                is_within=lambda path, base: os.path.commonpath((os.path.realpath(path), os.path.realpath(base))) == os.path.realpath(base),
                load_state=lambda: {"in_removal": {"Example": "2026-01-01"}},
                state_key=lambda lib, title: title,
                DRY_RUN=True,
                record_action=lambda *args, **kwargs: None,
                safe_move_directory=lambda *args: self.fail("Dry Run must never move media"),
            )
            with patch.object(manual_rescue, "begin_rescue", return_value=True), \
                 patch.object(manual_rescue, "end_rescue") as unlock, \
                 patch.object(manual_rescue.importlib, "import_module", return_value=auditor):
                ok, message, status = manual_rescue.rescue_title("Movies", "Example", "keep")
            self.assertTrue(ok, message)
            self.assertEqual(status, 200)
            self.assertTrue((removal / "Example").is_dir())
            self.assertFalse((keep / "Example").exists())
            unlock.assert_called_once()

    def test_symlink_source_is_rejected(self):
        with tempfile.TemporaryDirectory() as root:
            removal = Path(root) / "removal"
            keep = Path(root) / "keep"
            outside = Path(root) / "outside"
            for path in (removal, keep, outside):
                path.mkdir()
            (removal / "Example").symlink_to(outside, target_is_directory=True)
            auditor = SimpleNamespace(
                STATE_FILE=str(Path(root) / "state.json"),
                DRY_RUN=True,
                build_libraries=lambda: [{"name": "Movies", "removal": str(removal), "keep": str(keep)}],
                is_within=lambda *args: True,
            )
            with patch.object(manual_rescue, "begin_rescue", return_value=True), \
                 patch.object(manual_rescue, "end_rescue"), \
                 patch.object(manual_rescue.importlib, "import_module", return_value=auditor):
                self.assertEqual(manual_rescue.rescue_title("Movies", "Example", "keep")[2], 404)


if __name__ == "__main__":
    unittest.main()
