"""Post-audit Jellyfin refresh is opt-in and never runs without real moves."""
import requests


def test_refresh_is_disabled_by_default(make_auditor, posts):
    a = make_auditor()
    a.ca._successful_media_moves = 2
    a.ca.refresh_jellyfin_after_audit()
    assert posts.calls == []


def test_refresh_skips_dry_run(make_auditor, posts):
    a = make_auditor(DRY_RUN="true", JELLYFIN_REFRESH_AFTER_AUDIT="true")
    a.ca._successful_media_moves = 2
    a.ca.refresh_jellyfin_after_audit()
    assert posts.calls == []


def test_refresh_skips_when_nothing_moved(make_auditor, posts):
    a = make_auditor(JELLYFIN_REFRESH_AFTER_AUDIT="true")
    a.ca.refresh_jellyfin_after_audit()
    assert posts.calls == []


def test_refresh_posts_once_after_verified_move(make_auditor, posts):
    a = make_auditor(JELLYFIN_REFRESH_AFTER_AUDIT="true")
    a.make_folders()
    folder = a.add("Movies", "Example (2000)")
    lib = a.ca.build_libraries()[0]
    assert a.ca.safe_move_directory(str(folder), lib["holding"]) is None
    a.ca.refresh_jellyfin_after_audit()
    assert len(posts.calls) == 1
    assert posts.calls[0]["url"].endswith("/Library/Refresh")
    assert posts.calls[0]["allow_redirects"] is False
    assert a.actions("jellyfin_refresh")[0]["status"] == "done"


def test_refresh_failure_is_logged_without_crashing(make_auditor, monkeypatch):
    a = make_auditor(JELLYFIN_REFRESH_AFTER_AUDIT="true")
    a.ca._successful_media_moves = 1
    def fail(*args, **kwargs):
        raise requests.Timeout("timeout")
    monkeypatch.setattr(requests, "post", fail)
    a.ca.refresh_jellyfin_after_audit()
    assert a.actions("jellyfin_refresh_failed")[0]["status"] == "failed"
