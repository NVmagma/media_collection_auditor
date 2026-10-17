"""Read-only dashboard lifecycle visibility regressions."""
import os
import sys
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("WEB_SESSION_SECRET", "test-only-not-for-production")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import web


class DashboardLifecycleVisibilityTests(unittest.TestCase):
    def test_review_date_and_disabled_deletion_are_visible(self):
        since = (datetime.now() - timedelta(days=10)).isoformat()
        stages = {"Waiting": [], "Holding": [], "Keep": [],
                  "Removal": [{"title": "Example", "library": "Movies", "since": since}]}
        config = {"ALLOW_PERMANENT_DELETE": "false", "REMOVAL_DAYS": "7",
                  "ENABLE_MOVIES": "true", "ENABLE_TV": "false"}
        with web.app.test_request_context("/"), \
             patch.object(web, "load_actions", return_value=[]), \
             patch.object(web, "load_state", return_value={}), \
             patch.object(web, "load_config", return_value=config), \
             patch.object(web, "filesystem_stages", return_value=(stages, [])), \
             patch.object(web, "_dashboard_signals", return_value=None), \
             patch.object(web, "render_template", side_effect=lambda *args, **kwargs: kwargs):
            result = web.dashboard()
        item = result["stages"]["Removal"][0]
        self.assertEqual(item["decision"], "blocked")
        self.assertIn("master safety switch", item["decision_reason"])
        self.assertIsNotNone(item["next_review_date"])
        self.assertEqual(item["deadline_days"], 0)
        self.assertEqual(result["preview"], [])


if __name__ == "__main__":
    unittest.main()
