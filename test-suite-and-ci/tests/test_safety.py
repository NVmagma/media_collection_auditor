"""Safety net: preflight checks, fail-closed deletion, verified moves, honest action status, run summary."""
import json
import os
import shutil

import pytest
import requests

DISCORD = "https://discord.test/api/webhooks/123/secret-token"


# ---------------- helpers ----------------

def seed(a, section, key, days):
    """Write a state entry `days` old (creating the state file if needed)."""
    a.logs.mkdir(exist_ok=True)
    state_file = a.logs / "auditor_state.json"
    if not state_file.exists():
        state_file.write_text("{}")
    a.set_state(section, key, days)


class Resp:
    def __init__(self, body=None):
        self.status_code = 200
        self._body = body

    def json(self):
        return self._body

    def raise_for_status(self):
        pass


class FakeRadarr:
    """A pretend Radarr. entries are its movies; it records every PUT and DELETE the script sends."""

    def __init__(self, monkeypatch, entries, removes_on_delete=None, fail_put=False, fail_delete=False):
        self.entries = entries
        self.puts, self.deletes = [], []
        self.removes_on_delete = removes_on_delete or {}     # movie id -> folder to remove when deleted
        self.fail_put, self.fail_delete = fail_put, fail_delete
        monkeypatch.setattr(requests, "get", self.get)
        monkeypatch.setattr(requests, "put", self.put)
        monkeypatch.setattr(requests, "delete", self.delete)

    def get(self, url, **kwargs):
        return Resp(self.entries if url.endswith("/api/v3/movie") else {})

    def put(self, url, **kwargs):
        if self.fail_put:
            raise requests.ConnectionError("radarr is down")
        self.puts.append({"url": url, **kwargs})
        return Resp(kwargs.get("json"))

    def delete(self, url, **kwargs):
        if self.fail_delete:
            raise requests.ConnectionError("radarr is down")
        self.deletes.append(url)
        movie_id = int(url.rsplit("/", 1)[1])
        if movie_id in self.removes_on_delete:
            shutil.rmtree(self.removes_on_delete[movie_id])
        return Resp()


RADARR_ENV = {"RADARR_URL": "http://radarr.test", "RADARR_API_KEY": "key"}


# ---------------- preflight: folders ----------------

def test_missing_folder_stops_the_run_before_anything_moves(make_auditor):
    a = make_auditor()
    a.add("Movies", "Loved (2000)")
    a.movie("Loved (2000)", favorite=True)                       # would move to Movies_keep, which doesn't exist

    with pytest.raises(SystemExit) as stopped:
        a.ca.run_once()

    assert "PREFLIGHT FAILED" in str(stopped.value) and "keep folder does not exist" in str(stopped.value)
    assert a.where("Loved (2000)") == "Movies"
    assert not (a.media / "Movies_keep").exists()                # and it was NOT quietly created


def test_destination_folder_is_never_created_by_a_move(make_auditor, tmp_path):
    a = make_auditor()
    folder = a.add("Movies", "Loved (2000)")
    error = a.ca.safe_move_directory(str(folder), str(tmp_path / "an-unmounted-share"))

    assert "missing" in error
    assert not (tmp_path / "an-unmounted-share").exists()
    assert folder.is_dir()


def test_overlapping_folders_are_rejected(make_auditor, tmp_path):
    a = make_auditor(RADARR_HOLDING_PATH=tmp_path / "media" / "Movies" / "hold")   # inside Transient
    with pytest.raises(SystemExit) as stopped:
        a.run()

    assert "overlap" in str(stopped.value)


def test_a_folder_used_for_two_purposes_is_rejected(make_auditor, tmp_path):
    a = make_auditor(RADARR_KEEP_PATH=tmp_path / "media" / "Movies_hold")          # same as Holding
    with pytest.raises(SystemExit) as stopped:
        a.run()

    assert "same or overlap" in str(stopped.value)


def test_two_libraries_may_not_share_a_folder(make_auditor, tmp_path):
    a = make_auditor(ENABLE_TV="true", SONARR_KEEP_PATH=tmp_path / "media" / "Movies_keep")
    with pytest.raises(SystemExit) as stopped:
        a.run()

    assert "same as the Movies keep folder" in str(stopped.value)


def test_unwritable_folder_is_reported(make_auditor, monkeypatch):
    a = make_auditor()
    a.make_folders()
    monkeypatch.setattr(a.ca.os, "access", lambda path, mode: not str(path).endswith("Movies_keep"))
    with pytest.raises(SystemExit) as stopped:
        a.ca.run_once()

    assert "not writable" in str(stopped.value)


def test_nothing_enabled_is_an_error(make_auditor):
    a = make_auditor(ENABLE_MOVIES="false")
    with pytest.raises(SystemExit) as stopped:
        a.run()

    assert "No libraries are enabled" in str(stopped.value)


def test_folders_on_different_filesystems_are_refused_by_default(make_auditor, monkeypatch):
    a = make_auditor()
    a.make_folders()
    monkeypatch.setattr(a.ca, "filesystem_id", lambda path: 2 if str(path).endswith("Movies_keep") else 1)
    with pytest.raises(SystemExit) as stopped:
        a.ca.run_once()

    assert "different filesystems" in str(stopped.value)


def test_different_filesystems_can_be_accepted_with_a_warning(make_auditor, monkeypatch, capsys):
    a = make_auditor(ALLOW_CROSS_FILESYSTEM_MOVES="true")
    a.make_folders()
    monkeypatch.setattr(a.ca, "filesystem_id", lambda path: 2 if str(path).endswith("Movies_keep") else 1)
    a.ca.run_once()

    assert "[PREFLIGHT WARNING]" in capsys.readouterr().out


# ---------------- preflight: services ----------------

def test_unreachable_jellyfin_is_reported_without_the_address(make_auditor):
    a = make_auditor(JELLYFIN_HOST_URL="http://10.9.8.7:8096")

    def down(path, params=None):
        raise requests.ConnectionError("no route to 10.9.8.7")
    a.ca.jellyfin_get = down
    errors, warnings = a.real_check_services(a.ca.build_libraries())

    assert errors == ["Cannot reach Jellyfin (ConnectionError). Check JELLYFIN_HOST_URL."]
    assert "10.9.8.7" not in " ".join(errors)


def test_a_rejected_jellyfin_key_is_reported(make_auditor):
    a = make_auditor()

    def rejected(path, params=None):
        raise SystemExit("[ERROR] Jellyfin rejected the token (401). Token length seen: 5 chars.")
    a.ca.jellyfin_get = rejected
    errors, _ = a.real_check_services(a.ca.build_libraries())

    assert errors and "rejected the token" in errors[0]


def test_unreachable_radarr_is_reported_without_the_address(make_auditor):
    a = make_auditor(**RADARR_ENV)
    a.ca.jellyfin_get = lambda path, params=None: []

    def down():
        raise requests.ConnectionError("no route to radarr.test")
    a.ca.radarr.check = down
    errors, _ = a.real_check_services(a.ca.build_libraries())

    assert errors == ["Cannot reach Radarr (ConnectionError). Check RADARR_URL and RADARR_API_KEY."]


def test_unconfigured_radarr_is_a_warning_not_an_error(make_auditor):
    a = make_auditor()
    a.ca.jellyfin_get = lambda path, params=None: []
    errors, warnings = a.real_check_services(a.ca.build_libraries())

    assert errors == []
    assert "Radarr is not configured" in warnings[0]


def test_healthy_services_pass_cleanly(make_auditor):
    a = make_auditor(**RADARR_ENV)
    a.ca.jellyfin_get = lambda path, params=None: []
    a.ca.radarr.check = lambda: None

    assert a.real_check_services(a.ca.build_libraries()) == ([], [])


def test_a_service_failure_stops_the_run_before_anything_moves(make_auditor):
    a = make_auditor()
    a.add("Movies", "Loved (2000)")
    a.movie("Loved (2000)", favorite=True)
    a.make_folders()
    a.ca.check_services = lambda libs: (["Cannot reach Jellyfin (ConnectionError)."], [])

    with pytest.raises(SystemExit):
        a.ca.run_once()

    assert a.where("Loved (2000)") == "Movies"


# ---------------- configuration validation ----------------

@pytest.mark.parametrize("name, value", [
    ("HOLDING_DAYS", "0"), ("REMOVAL_DAYS", "0"), ("HOLDING_DAYS", "abc"), ("MOVIE_WAIT_DAYS", "-3"),
    ("MAX_ACTIONS_PER_RUN", "-1"), ("RUN_INTERVAL_HOURS", "-5"), ("RUN_INTERVAL_HOURS", "soon"),
    ("ENABLE_TV", "maybe"), ("DRY_RUN", "perhaps"),
])
def test_bad_settings_stop_the_script_with_a_clear_message(make_auditor, name, value):
    with pytest.raises(SystemExit) as stopped:
        make_auditor(**{name: value})

    assert "CONFIG ERROR" in str(stopped.value) and name in str(stopped.value)


@pytest.mark.parametrize("value", ["true", "TRUE", "yes", "1", "on"])
def test_true_can_be_written_several_ways(make_auditor, value):
    assert make_auditor(ENABLE_TV=value).ca.ENABLE_TV is True


# ---------------- deletion fails closed ----------------

def overdue_in_removal(a, name="Overdue (1996)", extra_bytes=0):
    folder = a.add("Movies_removal", name)
    if extra_bytes:
        (folder / "big.mkv").write_bytes(b"0" * extra_bytes)
    seed(a, "in_removal", name, 30)
    a.movie(name)  # Verified unprotected Jellyfin title; deletion policy is tested separately.
    return folder


def test_unknown_title_is_not_deleted_unless_you_opt_in(make_auditor):
    a = make_auditor(ALLOW_FILESYSTEM_DELETE="false")
    folder = overdue_in_removal(a)
    a.run()

    assert folder.is_dir()
    skipped = a.actions("delete_skipped")
    assert len(skipped) == 1 and skipped[0]["status"] == "skipped"
    assert "ALLOW_FILESYSTEM_DELETE" in skipped[0]["detail"]
    assert a.actions("delete") == []


def test_script_deletion_is_off_by_default(make_auditor):
    """The test fixtures turn it on for convenience, so check the real default explicitly."""
    assert make_auditor(ALLOW_FILESYSTEM_DELETE="").ca.ALLOW_FILESYSTEM_DELETE is False


def test_opting_in_lets_the_script_delete_by_itself(make_auditor):
    a = make_auditor(ALLOW_FILESYSTEM_DELETE="true")
    overdue_in_removal(a)
    a.run()

    assert a.where("Overdue (1996)") == "GONE"
    assert a.actions("delete")[0]["status"] == "done"


def test_title_unknown_to_radarr_is_not_deleted_even_though_radarr_is_configured(make_auditor, monkeypatch):
    a = make_auditor(ALLOW_FILESYSTEM_DELETE="false", **RADARR_ENV)
    radarr = FakeRadarr(monkeypatch, entries=[])
    folder = overdue_in_removal(a)
    a.run()

    assert folder.is_dir() and radarr.deletes == []
    assert "not found in Radarr" in a.actions("delete_skipped")[0]["detail"]


def test_title_known_to_radarr_is_deleted_through_radarr(make_auditor, monkeypatch):
    a = make_auditor(ALLOW_FILESYSTEM_DELETE="false", **RADARR_ENV)
    folder = overdue_in_removal(a)
    radarr = FakeRadarr(monkeypatch, entries=[{"id": 7, "path": "/data/removal/Overdue (1996)"}],
                        removes_on_delete={7: folder})
    a.run()

    assert radarr.deletes == ["http://radarr.test/api/v3/movie/7"]
    assert a.where("Overdue (1996)") == "GONE"
    assert a.actions("delete")[0]["status"] == "done"


def test_radarr_saying_yes_but_leaving_the_folder_is_flagged_and_retried(make_auditor, monkeypatch):
    a = make_auditor(**RADARR_ENV)
    folder = overdue_in_removal(a)
    FakeRadarr(monkeypatch, entries=[{"id": 7, "path": "/data/removal/Overdue (1996)"}])   # delete does nothing
    a.run()

    assert folder.is_dir()
    failed = a.actions("delete_failed")[0]
    assert failed["status"] == "failed" and "still there" in failed["detail"]
    assert "Overdue (1996)" in a.state()["in_removal"]            # kept, so the next run tries again


def test_two_radarr_entries_with_the_same_folder_name_block_deletion(make_auditor, monkeypatch):
    a = make_auditor(**RADARR_ENV)
    folder = overdue_in_removal(a)
    radarr = FakeRadarr(monkeypatch, entries=[{"id": 1, "path": "/a/Overdue (1996)"},
                                              {"id": 2, "path": "/b/Overdue (1996)"}])
    a.run()

    assert folder.is_dir() and radarr.deletes == []
    assert "2 Radarr entries" in a.actions("delete_skipped")[0]["detail"]


def test_a_radarr_error_while_deleting_is_a_recorded_failure_not_a_crash(make_auditor, monkeypatch):
    a = make_auditor(**RADARR_ENV)
    folder = overdue_in_removal(a)
    FakeRadarr(monkeypatch, entries=[{"id": 7, "path": "/x/Overdue (1996)"}], fail_delete=True)
    a.run()

    assert folder.is_dir()
    assert a.actions("delete_failed")[0]["status"] == "failed"
    assert a.actions("run_complete")


def test_paths_outside_the_removal_folder_are_never_deleted(make_auditor):
    a = make_auditor()
    a.make_folders()
    precious = a.add("Movies_keep", "Precious (2000)")
    lib = a.ca.build_libraries()[0]

    assert a.ca.remove_media(lib, "Precious (2000)", str(precious)) is False
    assert precious.is_dir()
    assert "not strictly inside the Removal folder" in a.actions("delete_skipped")[0]["detail"]


def test_a_symlink_in_removal_cannot_be_used_to_delete_something_else(make_auditor):
    a = make_auditor()
    a.make_folders()
    precious = a.add("Movies_keep", "Precious (2000)")
    os.symlink(precious, a.media / "Movies_removal" / "Precious (2000)")
    seed(a, "in_removal", "Precious (2000)", 30)
    a.movie("Precious (2000)")
    a.run()

    assert (precious / "video.mkv").exists()
    assert a.actions("delete_skipped")


def test_dry_run_never_asks_radarr_to_delete(make_auditor, monkeypatch):
    a = make_auditor(DRY_RUN="true", **RADARR_ENV)
    folder = overdue_in_removal(a)
    radarr = FakeRadarr(monkeypatch, entries=[{"id": 7, "path": "/data/removal/Overdue (1996)"}],
                        removes_on_delete={7: folder})
    a.run()

    assert radarr.deletes == [] and radarr.puts == []
    assert folder.is_dir()
    assert a.actions("delete")[0]["status"] == "planned"


def test_dry_run_deletes_nothing_even_with_filesystem_delete_enabled(make_auditor):
    a = make_auditor(DRY_RUN="true", ALLOW_FILESYSTEM_DELETE="true")
    folder = overdue_in_removal(a)
    a.run()

    assert folder.is_dir()
    assert a.actions("delete")[0]["status"] == "planned"


# ---------------- moves are verified and failures are honest ----------------

def undecided_movie(a, name="Slow Movie (2000)"):
    folder = a.add("Movies", name)
    a.movie(name)
    seed(a, "first_seen", name, 40)
    return folder


def test_a_failed_move_is_recorded_and_the_lifecycle_does_not_advance(make_auditor, monkeypatch):
    a = make_auditor()
    folder = undecided_movie(a)

    def boom(src, dst):
        raise OSError("disk full")
    monkeypatch.setattr(a.ca.shutil, "move", boom)
    a.run()

    assert folder.is_dir()
    failed = a.actions("move_failed")[0]
    assert failed["status"] == "failed" and "disk full" in failed["detail"]
    assert a.actions("hold") == []                                # no false "moved" entry
    assert "Slow Movie (2000)" not in a.state()["queued"]         # and no clock started


def test_a_move_that_silently_did_nothing_is_caught(make_auditor, monkeypatch):
    a = make_auditor()
    folder = undecided_movie(a)
    monkeypatch.setattr(a.ca.shutil, "move", lambda src, dst: None)
    a.run()

    assert folder.is_dir()
    assert "did not complete" in a.actions("move_failed")[0]["detail"]


def test_an_existing_destination_is_a_reported_failure(make_auditor):
    a = make_auditor()
    undecided_movie(a)
    a.add("Movies_hold", "Slow Movie (2000)")
    a.run()

    assert "already exists" in a.actions("move_failed")[0]["detail"]


def test_failed_moves_do_not_use_up_the_action_cap(make_auditor):
    a = make_auditor(MAX_ACTIONS_PER_RUN=1)
    for name in ("A (2000)", "B (2000)", "C (2000)"):
        undecided_movie(a, name)
    a.add("Movies_hold", "A (2000)")                               # A and B can't move: destination exists
    a.add("Movies_hold", "B (2000)")
    a.run()

    assert a.where("C (2000)") == "Movies_hold"                    # C still got its turn
    assert len(a.actions("hold")) == 1


# ---------------- Radarr stays in sync, and its failures are not fatal ----------------

def test_radarr_is_unmonitored_when_a_title_enters_holding(make_auditor, monkeypatch):
    a = make_auditor(**RADARR_ENV)
    undecided_movie(a)
    radarr = FakeRadarr(monkeypatch, entries=[{"id": 3, "path": "/data/movies/Slow Movie (2000)", "monitored": True}])
    a.run()

    sent = radarr.puts[0]
    assert sent["url"] == "http://radarr.test/api/v3/movie/3"
    assert sent["json"]["monitored"] is False
    assert sent["json"]["path"] == str(a.media / "Movies_hold" / "Slow Movie (2000)")
    assert sent["params"] == {"moveFiles": "false"}


def test_radarr_is_monitored_again_when_a_title_is_rescued(make_auditor, monkeypatch):
    a = make_auditor(**RADARR_ENV)
    a.add("Movies_hold", "Saved (2000)")
    a.movie("Saved (2000)", favorite=True)
    radarr = FakeRadarr(monkeypatch, entries=[{"id": 4, "path": "/data/hold/Saved (2000)", "monitored": False}])
    a.run()

    assert radarr.puts[0]["json"]["monitored"] is True
    assert radarr.puts[0]["json"]["path"] == str(a.media / "Movies_keep" / "Saved (2000)")


def test_a_radarr_failure_after_a_move_is_recorded_and_the_run_continues(make_auditor, monkeypatch):
    a = make_auditor(**RADARR_ENV)
    undecided_movie(a, "First (2000)")
    undecided_movie(a, "Second (2000)")
    FakeRadarr(monkeypatch, entries=[{"id": 1, "path": "/x/First (2000)"}, {"id": 2, "path": "/x/Second (2000)"}],
               fail_put=True)
    a.run()

    assert a.where("First (2000)") == "Movies_hold" and a.where("Second (2000)") == "Movies_hold"
    assert len(a.actions("arr_sync_failed")) == 2
    assert set(a.state()["queued"]) == {"First (2000)", "Second (2000)"}      # the moves were still remembered


def test_progress_is_saved_even_if_a_run_crashes_half_way(make_auditor):
    a = make_auditor(ENABLE_TV="true")
    undecided_movie(a)

    def only_movies(jellyfin_type):
        if jellyfin_type == "Series":
            raise RuntimeError("Jellyfin fell over")
        return a.signals[jellyfin_type]
    a.ca.get_signals = only_movies

    with pytest.raises(RuntimeError):
        a.run()

    assert a.where("Slow Movie (2000)") == "Movies_hold"
    assert "Slow Movie (2000)" in a.state()["queued"]


# ---------------- the action log, summary, and sizes ----------------

def test_dry_run_actions_are_marked_planned(make_auditor):
    a = make_auditor(DRY_RUN="true")
    undecided_movie(a)
    a.run()

    assert {r["status"] for r in a.actions("hold")} == {"planned"}


def test_real_actions_are_marked_done(make_auditor):
    a = make_auditor()
    undecided_movie(a)
    a.run()

    assert {r["status"] for r in a.actions("hold")} == {"done"}


def test_failed_actions_are_marked_failed(make_auditor, monkeypatch):
    a = make_auditor()
    undecided_movie(a)
    monkeypatch.setattr(a.ca.shutil, "move", lambda src, dst: (_ for _ in ()).throw(OSError("nope")))
    a.run()

    assert {r["status"] for r in a.actions("move_failed")} == {"failed"}
    assert a.actions("hold") == []


def test_run_summary_counts_everything(make_auditor, capsys):
    a = make_auditor(DRY_RUN="true")
    a.add("Movies", "Loved (2000)")
    a.movie("Loved (2000)", favorite=True)
    undecided_movie(a)
    a.add("Movies", "Waiting (2026)")
    a.movie("Waiting (2026)")
    a.run()
    output = capsys.readouterr().out

    assert "Run summary [DRY RUN - nothing was changed]" in output
    assert "Waiting in Transient:" in output
    summary = output[output.index("Run summary"):]
    row = lambda label: next(line for line in summary.splitlines() if label in line).split(":")[-1].strip()
    assert row("Waiting in Transient") == "1"
    assert row("Favorites sent to Keep") == "1"
    assert row("Sent to Holding") == "1"


def test_space_to_be_freed_is_reported(make_auditor, capsys):
    a = make_auditor()
    overdue_in_removal(a, extra_bytes=2048)
    a.run()
    output = capsys.readouterr().out

    assert "2.0 KB" in output
    assert a.actions("delete")[0]["size_bytes"] == 2049


def test_notification_shows_failures_and_freed_space(make_auditor, posts, monkeypatch):
    a = make_auditor(NOTIFY_DISCORD_WEBHOOK_URL=DISCORD)
    overdue_in_removal(a, extra_bytes=2048)
    undecided_movie(a)
    monkeypatch.setattr(a.ca.shutil, "move", lambda src, dst: (_ for _ in ()).throw(OSError("disk full")))
    a.run()

    content = posts.calls[0]["json"]["content"]
    assert "Permanently deleted (1, 2.0 KB)" in content
    assert "Could not move (1)" in content
    assert "disk full" in content


@pytest.mark.parametrize("size, text", [(0, "0 B"), (1023, "1023 B"), (1536, "1.5 KB"),
                                        (5 * 1024 ** 3, "5.0 GB"), (2 * 1024 ** 4, "2.0 TB")])
def test_human_readable_sizes(make_auditor, size, text):
    assert make_auditor().ca.human_size(size) == text


def test_dry_run_move_never_touches_the_disk_or_radarr(make_auditor, monkeypatch):
    a = make_auditor(DRY_RUN="true", **RADARR_ENV)
    folder = undecided_movie(a)
    radarr = FakeRadarr(monkeypatch, entries=[{"id": 3, "path": "/data/movies/Slow Movie (2000)", "monitored": True}])
    a.run()

    assert folder.is_dir()
    assert radarr.puts == [] and radarr.deletes == []
