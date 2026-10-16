"""Authorization and origin safety checks for the Flask dashboard.

Run with: python -m unittest discover -s tests -v
No Jellyfin server, media mounts, or live API calls are required.
"""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("WEB_SESSION_SECRET", "test-only-not-for-production")
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

import web


class WebSecurityTests(unittest.TestCase):
    def setUp(self):
        self.client = web.app.test_client()

    def test_health_is_public(self):
        self.assertEqual(self.client.get("/health").status_code, 200)

    def test_login_page_is_public(self):
        self.assertEqual(self.client.get("/login").status_code, 200)

    def test_anonymous_dashboard_redirects_to_login(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_anonymous_api_cannot_run_audit(self):
        self.assertEqual(self.client.post("/api/run-now").status_code, 401)

    def test_poster_folder_matching_movie_and_tv(self):
        movie = {"Path": "/media/movies/Interstellar (2014)/Interstellar.mkv"}
        series = {"Path": "/media/tv/The Expanse (2015)"}
        self.assertEqual(web._poster_folder(movie, "Movie"), "interstellar (2014)")
        self.assertEqual(web._poster_folder(series, "Series"), "the expanse (2015)")

    def test_poster_endpoint_uses_folder_match(self):
        from unittest.mock import Mock
        response = Mock(status_code=200, content=b"fake-image",
                        headers={"Content-Type": "image/jpeg"})
        with patch.object(web, "current_user", return_value={"name": "Viewer", "admin": False}), \
             patch.object(web, "load_config", return_value={"JELLYFIN_HOST_URL": "http://jellyfin:8096", "JELLYFIN_API_TOKEN": "test-token"}), \
             patch.object(web, "_poster_index", return_value={"interstellar (2014)": "item-id"}), \
             patch.object(web.requests, "get", return_value=response) as get:
            result = self.client.get("/api/poster?library=Movies&title=Interstellar%20(2014)")
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.data, b"fake-image")
            self.assertIn("/Items/item-id/Images/Primary", get.call_args.args[0])

    def test_friendly_dates(self):
        self.assertEqual(web.friendly_date("2026-10-15T20:27:17.166650"), "Oct 15, 2026")
        self.assertEqual(web.friendly_date("legacy"), "legacy")

    def test_jellyfin_link_requires_login(self):
        self.assertEqual(self.client.get("/api/jellyfin-link?library=Movies&title=Example").status_code, 401)

    def test_jellyfin_link_redirects_to_item(self):
        with patch.object(web, "current_user", return_value={"name": "Viewer", "admin": False}), patch.object(web, "_jellyfin_item_id", return_value=("http://jellyfin:8096", "abc123")):
            response = self.client.get("/api/jellyfin-link?library=Movies&title=Example")
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.headers["Location"], "http://jellyfin:8096/web/index.html#!/details?id=abc123")

    def test_jellyfin_link_missing_item(self):
        with patch.object(web, "current_user", return_value={"name": "Viewer", "admin": False}), patch.object(web, "_jellyfin_item_id", return_value=("http://jellyfin:8096", None)):
            self.assertEqual(self.client.get("/api/jellyfin-link?library=Movies&title=Missing").status_code, 404)

    def test_anonymous_cannot_request_poster(self):
        self.assertEqual(self.client.get("/api/poster?library=Movies&title=Example").status_code, 401)

    def test_poster_missing_credentials_fails_closed(self):
        with patch.object(web, "current_user", return_value={"name": "Viewer", "admin": False}), \
             patch.object(web, "load_config", return_value={}), \
             patch.dict(os.environ, {"JELLYFIN_API_TOKEN": "", "JELLYFIN_HOST_URL": ""}):
            self.assertEqual(self.client.get("/api/poster?library=Movies&title=Example").status_code, 404)

    def test_poster_rejects_invalid_library(self):
        with patch.object(web, "current_user", return_value={"name": "Viewer", "admin": False}):
            self.assertEqual(self.client.get("/api/poster?library=Other&title=Example").status_code, 400)

    def test_anonymous_api_cannot_rescue(self):
        self.assertEqual(self.client.post("/api/rescue", json={}).status_code, 401)

    def test_read_only_user_cannot_mutate(self):
        with patch.object(web, "current_user", return_value={"name": "Viewer", "admin": False}):
            self.assertEqual(self.client.get("/settings").status_code, 403)
            self.assertEqual(self.client.post("/api/run-now").status_code, 403)
            self.assertEqual(self.client.post("/api/rescue", json={}).status_code, 403)
            self.assertEqual(self.client.post("/api/test-connection/jellyfin").status_code, 403)

    def test_read_only_user_can_view_dashboard(self):
        with patch.object(web, "current_user", return_value={"name": "Viewer", "admin": False}), \
             patch.object(web, "load_actions", return_value=[]), \
             patch.object(web, "load_state", return_value={}), \
             patch.object(web, "load_config", return_value={"DRY_RUN": "true"}), \
             patch.object(web, "snapshot", return_value={"running": False, "queued": False, "last_result": None, "last_finished": None, "next_run": None, "movies_processed": None, "tv_processed": None}), \
             patch.object(web, "read_history", return_value=[]):
            response = self.client.get("/")
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"TV Shows", response.data)
            self.assertIn(b"Movies", response.data)

    def test_dashboard_preview_is_read_only_and_explains_stages(self):
        with patch.object(web, "current_user", return_value={"name": "Viewer", "admin": False}), \
             patch.object(web, "load_actions", return_value=[]), \
             patch.object(web, "load_state", return_value={"first_seen": {"Example (2020)": "2020-01-01T00:00:00"}, "queued": {}, "in_removal": {}, "keep_seen": {}}), \
             patch.object(web, "load_config", return_value={"DRY_RUN": "true"}), \
             patch.object(web, "snapshot", return_value={"running": False, "queued": False, "last_result": None, "last_finished": None, "next_run": None, "movies_processed": None, "tv_processed": None}), \
             patch.object(web, "read_history", return_value=[]):
            response = self.client.get("/")
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"Audit Preview", response.data)
            self.assertIn(b"Review for move to Holding", response.data)
            self.assertIn(b"Why this stage?", response.data)
            self.assertIn(b"not a simulation", response.data)

    def test_admin_requests_reject_missing_origin(self):
        with patch.object(web, "current_user", return_value={"name": "Admin", "admin": True}):
            self.assertEqual(self.client.post("/api/run-now").status_code, 403)
            self.assertEqual(self.client.post("/api/rescue", json={}).status_code, 403)

    def test_admin_requests_reject_foreign_origin(self):
        with patch.object(web, "current_user", return_value={"name": "Admin", "admin": True}):
            self.assertEqual(self.client.post("/api/run-now", headers={"Origin": "https://evil.example"}).status_code, 403)

    def test_admin_run_now_calls_queue_only_after_origin_check(self):
        with patch.object(web, "current_user", return_value={"name": "Admin", "admin": True}), \
             patch.object(web, "request_run", return_value=True) as queue:
            response = self.client.post("/api/run-now", headers={"Origin": "http://localhost"})
            self.assertEqual(response.status_code, 202)
            queue.assert_called_once()

    def test_admin_rescue_dispatches_validated_request(self):
        with patch.object(web, "current_user", return_value={"name": "Admin", "admin": True}), \
             patch.object(web, "rescue_title", return_value=(True, "Dry Run preview recorded; no media moved.", 200)) as rescue:
            response = self.client.post("/api/rescue", json={"library": "TV", "title": "Example", "destination": "keep"}, headers={"Origin": "http://localhost"})
            self.assertEqual(response.status_code, 200)
            rescue.assert_called_once_with("TV", "Example", "keep")


if __name__ == "__main__":
    unittest.main()
