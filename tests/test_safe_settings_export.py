"""Safe configuration export must never disclose secrets or infrastructure endpoints."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("WEB_SESSION_SECRET", "test-only-not-for-production")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from config_store import redacted_config
from web import app


class SafeSettingsExportTests(unittest.TestCase):
    def test_allowlist_excludes_secrets_and_locations(self):
        config = {
            "JELLYFIN_API_TOKEN": "secret-jellyfin",
            "RADARR_API_KEY": "secret-radarr",
            "SONARR_API_KEY": "secret-sonarr",
            "NOTIFY_DISCORD_WEBHOOK_URL": "https://example.invalid/secret-hook",
            "JELLYFIN_HOST_URL": "http://private-jellyfin",
            "MEDIA_PATH": "/private/media",
            "DRY_RUN": "false",
            "MOVIE_WAIT_DAYS": "30",
        }
        safe = redacted_config(config)
        self.assertEqual(safe, {"DRY_RUN": "false", "MOVIE_WAIT_DAYS": "30"})
        for secret in ("secret-jellyfin", "secret-radarr", "secret-sonarr",
                       "secret-hook", "private-jellyfin", "/private/media"):
            self.assertNotIn(secret, str(safe))

    def test_export_requires_admin(self):
        with app.test_request_context("/settings/export-safe"):
            with patch("web.g") as user:
                user.user = {"admin": False}
                from web import export_safe_settings
                self.assertEqual(export_safe_settings().status_code, 403)

    def test_export_is_non_cacheable_and_redacted(self):
        with app.test_request_context("/settings/export-safe"):
            with patch("web.g") as user, patch("web.load_config", return_value={
                "JELLYFIN_API_TOKEN": "private-token", "DRY_RUN": "false"}):
                user.user = {"admin": True}
                from web import export_safe_settings
                response = export_safe_settings()
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                self.assertNotIn(b"private-token", response.get_data())
                self.assertIn(b"DRY_RUN", response.get_data())


if __name__ == "__main__":
    unittest.main()
