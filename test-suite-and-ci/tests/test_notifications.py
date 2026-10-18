"""Optional notifications: Discord, ntfy, and a generic webhook."""
import json

import pytest
import requests

DISCORD = "https://discord.test/api/webhooks/123/secret-token"
NTFY = "https://ntfy.test/media-auditor"
HOOK = "https://hooks.test/auditor"


def seed_undecided_movie(a, name="Slow Movie (2000)"):
    a.logs.mkdir(exist_ok=True)
    (a.logs / "auditor_state.json").write_text(json.dumps({"first_seen": {}}))
    a.add("Movies", name)
    a.movie(name)
    a.set_state("first_seen", name, 40)


def test_nothing_is_sent_when_no_target_is_configured(make_auditor, posts):
    a = make_auditor()
    seed_undecided_movie(a)
    a.run()

    assert posts.calls == []


def test_discord_message_lists_what_moved(make_auditor, posts):
    a = make_auditor(NOTIFY_DISCORD_WEBHOOK_URL=DISCORD)
    seed_undecided_movie(a)
    a.run()

    assert len(posts.calls) == 1
    call = posts.calls[0]
    assert call["url"] == DISCORD
    content = call["json"]["content"]
    assert "Media Auditor" in content
    assert "Moved to Leaving Soon (1)" in content
    assert "Movies: Slow Movie (2000)" in content
    assert "[DRY RUN]" not in content


def test_quiet_run_sends_nothing(make_auditor, posts):
    a = make_auditor(NOTIFY_DISCORD_WEBHOOK_URL=DISCORD)
    a.add("Movies", "Fresh (2026)")
    a.movie("Fresh (2026)")                                       # still inside its waiting period
    a.run()

    assert posts.calls == []


def test_digest_lists_what_is_still_in_holding(make_auditor, posts):
    a = make_auditor(NOTIFY_DISCORD_WEBHOOK_URL=DISCORD)
    a.logs.mkdir()
    (a.logs / "auditor_state.json").write_text(json.dumps({"queued": {}}))
    a.add("Movies_hold", "On The Way Out (1999)")
    a.movie("On The Way Out (1999)")
    a.set_state("queued", "On The Way Out (1999)", 5)             # 2 of 7 days left
    a.run()

    content = posts.calls[0]["json"]["content"]
    assert "Leaving Soon - favorite in Jellyfin to keep (1)" in content
    assert "On The Way Out (1999) (2 days left)" in content


def test_digest_can_be_turned_off(make_auditor, posts):
    a = make_auditor(NOTIFY_DISCORD_WEBHOOK_URL=DISCORD, NOTIFY_LEAVING_SOON_DIGEST="false")
    a.logs.mkdir()
    (a.logs / "auditor_state.json").write_text(json.dumps({"queued": {}}))
    a.add("Movies_hold", "On The Way Out (1999)")
    a.movie("On The Way Out (1999)")
    a.set_state("queued", "On The Way Out (1999)", 5)
    a.run()

    assert posts.calls == []


def test_dry_runs_are_silent_by_default(make_auditor, posts):
    a = make_auditor(DRY_RUN="true", NOTIFY_DISCORD_WEBHOOK_URL=DISCORD)
    seed_undecided_movie(a)
    a.run()

    assert posts.calls == []


def test_dry_run_messages_can_be_enabled_and_are_labelled(make_auditor, posts):
    a = make_auditor(DRY_RUN="true", NOTIFY_DISCORD_WEBHOOK_URL=DISCORD, NOTIFY_ON_DRY_RUN="true")
    seed_undecided_movie(a)
    a.run()

    assert "[DRY RUN]" in posts.calls[0]["json"]["content"]


def test_ntfy_gets_a_plain_text_body_with_title_and_token(make_auditor, posts):
    a = make_auditor(NOTIFY_NTFY_URL=NTFY, NOTIFY_NTFY_TOKEN="tk_abc")
    seed_undecided_movie(a)
    a.run()

    call = posts.calls[0]
    assert call["url"] == NTFY
    assert isinstance(call["data"], bytes) and b"Slow Movie (2000)" in call["data"]
    assert call["headers"]["Title"] == "Media Auditor"
    assert call["headers"]["Authorization"] == "Bearer tk_abc"


def test_ntfy_without_a_token_sends_no_auth_header(make_auditor, posts):
    a = make_auditor(NOTIFY_NTFY_URL=NTFY)
    seed_undecided_movie(a)
    a.run()

    assert "Authorization" not in posts.calls[0]["headers"]


def test_generic_webhook_receives_structured_json(make_auditor, posts):
    a = make_auditor(NOTIFY_WEBHOOK_URL=HOOK)
    seed_undecided_movie(a)
    a.run()

    payload = posts.calls[0]["json"]
    assert payload["dry_run"] is False
    assert payload["events"][0]["action"] == "hold"
    assert payload["events"][0]["folder"] == "Slow Movie (2000)"
    assert "Slow Movie (2000)" in payload["message"]


def test_all_three_targets_can_be_used_together(make_auditor, posts):
    a = make_auditor(NOTIFY_DISCORD_WEBHOOK_URL=DISCORD, NOTIFY_NTFY_URL=NTFY, NOTIFY_WEBHOOK_URL=HOOK)
    seed_undecided_movie(a)
    a.run()

    assert {c["url"] for c in posts.calls} == {DISCORD, NTFY, HOOK}


def test_a_failing_notification_never_breaks_the_run(make_auditor, monkeypatch, capsys):
    def broken(*args, **kwargs):
        raise requests.ConnectionError(f"could not reach {DISCORD}")
    monkeypatch.setattr(requests, "post", broken)
    a = make_auditor(NOTIFY_DISCORD_WEBHOOK_URL=DISCORD)
    seed_undecided_movie(a)
    a.run()                                                       # must not raise

    assert a.where("Slow Movie (2000)") == "Movies_hold"          # the real work still happened
    output = capsys.readouterr().out
    assert "[NOTIFY ERROR] Discord failed" in output
    assert "secret-token" not in output                           # webhook URLs are secrets: never print them


def test_http_errors_are_reported_without_the_url(make_auditor, monkeypatch, capsys):
    class Rejected:
        status_code = 404

        def raise_for_status(self):
            error = requests.HTTPError("404 for url " + DISCORD)
            error.response = self
            raise error
    monkeypatch.setattr(requests, "post", lambda url, **kw: Rejected())
    a = make_auditor(NOTIFY_DISCORD_WEBHOOK_URL=DISCORD)
    seed_undecided_movie(a)
    a.run()
    output = capsys.readouterr().out

    assert "HTTP 404" in output
    assert "secret-token" not in output


def test_long_messages_are_trimmed_to_fit_discord(make_auditor, posts):
    a = make_auditor(NOTIFY_DISCORD_WEBHOOK_URL=DISCORD, MAX_ACTIONS_PER_RUN=500)
    a.logs.mkdir()
    (a.logs / "auditor_state.json").write_text(json.dumps({"first_seen": {}}))
    for i in range(80):
        name = f"A Fairly Long Movie Title Number {i} (2000)"
        a.add("Movies", name)
        a.movie(name)
        a.set_state("first_seen", name, 40)
    a.run()

    content = posts.calls[0]["json"]["content"]
    assert len(content) < 2000
    assert "...and more" in content


def test_a_failed_run_sends_an_alert_and_still_raises(make_auditor, posts):
    a = make_auditor(NOTIFY_DISCORD_WEBHOOK_URL=DISCORD)

    def explode(jellyfin_type):
        raise RuntimeError("Jellyfin is down")
    a.ca.get_signals = explode
    a.make_folders()

    with pytest.raises(RuntimeError):
        a.ca.run_with_alerts()

    content = posts.calls[0]["json"]["content"]
    assert "Run failed (1)" in content
    assert "Jellyfin is down" in content
    assert a.actions("run_failed")


def test_failed_runs_are_silent_during_dry_runs(make_auditor, posts):
    a = make_auditor(DRY_RUN="true", NOTIFY_DISCORD_WEBHOOK_URL=DISCORD)
    a.ca.get_signals = lambda jellyfin_type: (_ for _ in ()).throw(RuntimeError("Jellyfin is down"))
    a.make_folders()

    with pytest.raises(RuntimeError):
        a.ca.run_with_alerts()

    assert posts.calls == []


def test_events_from_one_run_do_not_leak_into_the_next(make_auditor, posts):
    a = make_auditor(NOTIFY_DISCORD_WEBHOOK_URL=DISCORD)
    seed_undecided_movie(a)
    a.run()
    posts.calls.clear()
    a.run()                                                       # nothing new happens this time

    for call in posts.calls:
        assert "Moved to Leaving Soon" not in call["json"]["content"]


def test_test_notification_target_detection(make_auditor):
    assert make_auditor().ca.notifications_configured() is False
    assert make_auditor(NOTIFY_NTFY_URL=NTFY).ca.notifications_configured() is True


def test_send_notification_reports_whether_every_target_succeeded(make_auditor, posts, monkeypatch):
    a = make_auditor(NOTIFY_DISCORD_WEBHOOK_URL=DISCORD, NOTIFY_WEBHOOK_URL=HOOK)
    note = {"title": "t", "message": "m", "dry_run": False, "events": [], "leaving_soon": []}
    assert a.ca.send_notification(note) is True

    def fail_for_hook(url, **kwargs):
        if url == HOOK:
            raise requests.ConnectionError("down")
        return posts(url, **kwargs)
    monkeypatch.setattr(requests, "post", fail_for_hook)
    assert a.ca.send_notification(note) is False                  # one target failed -> not all succeeded
