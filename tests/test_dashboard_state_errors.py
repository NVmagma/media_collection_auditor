"""Dashboard must expose damaged tracking state instead of silently treating it as empty."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import web


class DashboardStateErrorTests(unittest.TestCase):
    def test_missing_state_is_allowed_for_new_installation(self):
        with tempfile.TemporaryDirectory() as root:
            with patch.object(web, "STATE_FILE", str(Path(root) / "missing.json")):
                self.assertEqual(web.load_state(), {})

    def test_valid_state_remains_visible(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "state.json"
            expected = {"keep_seen": {"Movie": "2026-01-01T00:00:00"}}
            path.write_text(json.dumps(expected), encoding="utf-8")
            with patch.object(web, "STATE_FILE", str(path)):
                self.assertEqual(web.load_state(), expected)

    def test_corrupt_state_raises_visible_error(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "state.json"
            path.write_text("{broken", encoding="utf-8")
            with patch.object(web, "STATE_FILE", str(path)):
                with self.assertRaisesRegex(RuntimeError, "tracking state is unreadable"):
                    web.load_state()

    def test_invalid_utf8_state_raises_visible_error(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "state.json"
            path.write_bytes(b"\\xff")
            with patch.object(web, "STATE_FILE", str(path)):
                with self.assertRaisesRegex(RuntimeError, "tracking state is unreadable"):
                    web.load_state()


if __name__ == "__main__":
    unittest.main()
