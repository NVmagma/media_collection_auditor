"""Master deletion gate and authenticated log export regression tests."""
import os
import sys
import tempfile
import io
import zipfile
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch, Mock

os.environ.setdefault("WEB_SESSION_SECRET", "test-only-not-for-production")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import collection_auditor as auditor
import web


class MasterDeletionTests(unittest.TestCase):
    def test_master_switch_defaults_disabled(self):
        self.assertFalse(auditor.ALLOW_PERMANENT_DELETE)

    def test_arr_delete_blocked_even_when_filesystem_delete_enabled(self):
        arr = Mock(enabled=True, name="Radarr")
        library = {"arr": arr, "name": "Movies", "removal": "/media/Movies_removal"}
        with patch.object(auditor, "ALLOW_PERMANENT_DELETE", False), \
             patch.object(auditor, "ALLOW_FILESYSTEM_DELETE", True), \
             patch.object(auditor, "DRY_RUN", False), \
             patch.object(auditor, "record_action") as record:
            self.assertFalse(auditor.remove_media(library, "Example", "/media/Movies_removal/Example"))
        arr.find.assert_not_called()
        arr.delete.assert_not_called()
        record.assert_called_once()

    def test_season_pruning_blocked_by_master_switch(self):
        library = {"arr": Mock(enabled=True)}
        with patch.object(auditor, "ALLOW_PERMANENT_DELETE", False), \
             patch.object(auditor, "list_folders") as listing:
            auditor.audit_keep_seasons(library, {}, {})
        listing.assert_not_called()


class LogExportTests(unittest.TestCase):
    def setUp(self):
        self.client = web.app.test_client()

    def test_anonymous_export_requires_login(self):
        self.assertEqual(self.client.get("/logs/export").status_code, 302)

    def test_viewer_cannot_export(self):
        with patch.object(web, "current_user", return_value={"name": "Viewer", "admin": False}):
            self.assertEqual(self.client.get("/logs/export").status_code, 403)

    def test_viewer_cannot_export_diagnostics(self):
        with patch.object(web, "current_user", return_value={"name": "Viewer", "admin": False}):
            self.assertEqual(self.client.get("/logs/diagnostics").status_code, 403)

    def test_diagnostics_excludes_secrets_and_state(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "actions.jsonl"
            path.write_text('{"action":"run_complete"}\\n')
            with patch.object(web, "current_user", return_value={"name": "Admin", "admin": True}), \\
                 patch.object(web, "ACTION_LOG_FILE", str(path)), \\
                 patch.object(web, "load_config", return_value={
                     "JELLYFIN_API_TOKEN": "DO-NOT-EXPORT-TOKEN",
                     "ALLOW_PERMANENT_DELETE": "false"}):
                response = self.client.get("/logs/diagnostics")
            self.assertEqual(response.status_code, 200)
            with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
                self.assertEqual(set(archive.namelist()), {"diagnostics.json", "recent_actions.jsonl"})
                report = json.loads(archive.read("diagnostics.json"))
                self.assertEqual(report["safety_settings"]["ALLOW_PERMANENT_DELETE"], "false")
                self.assertIn(b"run_complete", archive.read("recent_actions.jsonl"))
                self.assertNotIn(b"DO-NOT-EXPORT-TOKEN", response.data)

    def test_admin_can_export_persisted_jsonl(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "actions.jsonl"
            path.write_text('{"action":"run_complete"}\\n')
            with patch.object(web, "current_user", return_value={"name": "Admin", "admin": True}), \
                 patch.object(web, "ACTION_LOG_FILE", str(path)):
                response = self.client.get("/logs/export")
            self.assertEqual(response.status_code, 200)
            self.assertIn("attachment", response.headers["Content-Disposition"])
            self.assertIn(b"run_complete", response.data)


if __name__ == "__main__":
    unittest.main()
