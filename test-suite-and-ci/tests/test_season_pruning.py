"""Season pruning: keep only the latest season of favorited shows, unless protected by a tag."""
import datetime
import os

import pytest


def iso(days_ago):
    return (datetime.datetime.now() - datetime.timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%S.123Z")


def episode_files(spec):
    """spec = {season_number: days_ago_added}. Two episodes per season, plus one special (season 0)."""
    files, next_id = [], 1
    for season, days_ago in spec.items():
        for _ in range(2):
            files.append({"id": next_id, "seasonNumber": season, "dateAdded": iso(days_ago)})
            next_id += 1
    files.append({"id": 999, "seasonNumber": 0, "dateAdded": iso(900)})
    return files


class FakeSonarr:
    """Replaces the real Sonarr connection for one test and records what the script asked it to do."""

    def __init__(self, ca, files_by_show):
        self.pruned = []
        ca.sonarr.url, ca.sonarr.key = "http://sonarr.test", "key"
        ca.sonarr.find = lambda folder: {"id": 1, "path": f"/tv_keep/{folder}", "seasons": []} \
            if folder in files_by_show else None
        ca.sonarr.episode_files = lambda item: files_by_show[os.path.basename(item["path"])]
        ca.sonarr.prune_seasons = lambda item, seasons, files: self.pruned.append(
            (os.path.basename(item["path"]), seasons, len(files)))


@pytest.fixture
def setup(make_auditor):
    def _setup(files_by_show, tagged=(), **env):
        a = make_auditor(ENABLE_TV="true", ENABLE_SEASON_PRUNING="true", **env)
        sonarr = FakeSonarr(a.ca, files_by_show)
        a.logs.mkdir()
        (a.logs / "auditor_state.json").write_text('{"keep_seen": {}}')
        for show in files_by_show:
            a.add("TV_keep", show)
            a.show(show, favorite=True, keep_all=show in tagged)
            a.set_state("keep_seen", f"TV/{show}", 45)           # past the 30-day grace period
        return a, sonarr
    return _setup


def test_old_seasons_are_pruned_and_latest_is_kept(setup):
    a, sonarr = setup({"FROM (2022)": episode_files({1: 400, 2: 300, 3: 200})})
    a.run()

    assert sonarr.pruned == [("FROM (2022)", [1, 2], 4)]         # specials (season 0) are not touched
    assert a.actions("prune_seasons")[0]["detail"].endswith("kept season 3")


def test_keep_all_seasons_tag_prevents_pruning(setup):
    a, sonarr = setup({"Brooklyn Nine-Nine (2013)": episode_files({1: 900, 2: 800, 8: 700})},
                      tagged={"Brooklyn Nine-Nine (2013)"})
    a.run()

    assert sonarr.pruned == []


def test_single_season_show_is_left_alone(setup):
    a, sonarr = setup({"Short Show (2020)": episode_files({1: 100})})
    a.run()

    assert sonarr.pruned == []


def test_brand_new_season_delays_pruning(setup):
    a, sonarr = setup({"Premiere Show (2024)": episode_files({1: 300, 2: 2})})   # season 2 arrived 2 days ago
    a.run()

    assert sonarr.pruned == []


def test_new_season_delay_is_configurable(setup):
    a, sonarr = setup({"Premiere Show (2024)": episode_files({1: 300, 2: 2})}, SEASON_PRUNE_AFTER_NEW_SEASON_DAYS=1)
    a.run()

    assert sonarr.pruned == [("Premiere Show (2024)", [1], 2)]


def test_grace_period_protects_recently_kept_shows(setup):
    a, sonarr = setup({"New In Keep (2021)": episode_files({1: 300, 2: 100})})
    a.set_state("keep_seen", "TV/New In Keep (2021)", 3)         # only 3 days in Keep
    a.run()

    assert sonarr.pruned == []


def test_first_sighting_starts_the_grace_period(setup):
    a, sonarr = setup({"Brand New (2021)": episode_files({1: 300, 2: 100})})
    state = a.state()
    del state["keep_seen"]["TV/Brand New (2021)"]
    import json
    (a.logs / "auditor_state.json").write_text(json.dumps(state))
    a.run()

    assert sonarr.pruned == []
    assert "TV/Brand New (2021)" in a.state()["keep_seen"]


def test_show_unknown_to_jellyfin_is_skipped(setup):
    a, sonarr = setup({"Mystery (2019)": episode_files({1: 400, 2: 300})})
    a.signals["Series"].clear()                                   # Jellyfin has never heard of it
    a.run()

    assert sonarr.pruned == []


def test_show_unknown_to_sonarr_is_skipped(setup):
    a, sonarr = setup({"Ghost (2019)": episode_files({1: 400, 2: 300})})
    a.ca.sonarr.find = lambda folder: None
    a.run()

    assert sonarr.pruned == []


def test_pruning_counts_toward_the_action_cap(setup):
    shows = {f"Show {i} (2020)": episode_files({1: 400, 2: 300}) for i in range(5)}
    a, sonarr = setup(shows, MAX_ACTIONS_PER_RUN=2)
    a.run()

    assert len(sonarr.pruned) == 2


def test_pruning_is_off_unless_enabled(make_auditor):
    a = make_auditor(ENABLE_TV="true")                            # ENABLE_SEASON_PRUNING not set
    sonarr = FakeSonarr(a.ca, {"FROM (2022)": episode_files({1: 400, 2: 300, 3: 200})})
    a.add("TV_keep", "FROM (2022)")
    a.show("FROM (2022)", favorite=True)
    a.run()

    assert sonarr.pruned == []


def test_pruning_needs_sonarr(make_auditor, capsys):
    a = make_auditor(ENABLE_TV="true", ENABLE_SEASON_PRUNING="true")     # no SONARR_URL / key
    a.add("TV_keep", "FROM (2022)")
    a.show("FROM (2022)", favorite=True)
    a.run()

    assert "needs Sonarr" in capsys.readouterr().out
    assert (a.media / "TV_keep" / "FROM (2022)" / "video.mkv").exists()


def test_sonarr_dates_parse_with_and_without_fractions(make_auditor):
    ca = make_auditor().ca

    assert ca.parse_arr_date("2026-10-01T12:34:56Z") == datetime.datetime(2026, 10, 1, 12, 34, 56)
    assert ca.parse_arr_date("2026-10-01T12:34:56.789Z") == datetime.datetime(2026, 10, 1, 12, 34, 56)
    assert ca.parse_arr_date(None) is None
    assert ca.parse_arr_date("not a date") is None


# ---------------- the real requests sent to Sonarr (nothing stubbed except the network) ----------------

class Reply:
    status_code = 200

    def __init__(self, body=None):
        self._body = body

    def json(self):
        return self._body

    def raise_for_status(self):
        pass


class SonarrServer:
    """A pretend Sonarr that records, in order, every change the script asks for."""

    def __init__(self, monkeypatch, series, files, fail_delete=False):
        import requests
        self.series, self.files, self.fail_delete = series, files, fail_delete
        self.changes = []
        monkeypatch.setattr(requests, "get", self.get)
        monkeypatch.setattr(requests, "put", self.put)
        monkeypatch.setattr(requests, "delete", self.delete)

    def get(self, url, **kwargs):
        if url.endswith("/api/v3/series"):
            return Reply(self.series)
        if url.endswith("/api/v3/episodefile"):
            return Reply(self.files)
        return Reply({})

    def put(self, url, **kwargs):
        self.changes.append(("PUT", url, kwargs["json"]))
        return Reply(kwargs["json"])

    def delete(self, url, **kwargs):
        import requests
        if self.fail_delete:
            raise requests.ConnectionError("sonarr is down")
        self.changes.append(("DELETE", url))
        return Reply()


SONARR_ENV = {"ENABLE_TV": "true", "ENABLE_SEASON_PRUNING": "true",
              "SONARR_URL": "http://sonarr.test", "SONARR_API_KEY": "key"}


def prunable_show(a, monkeypatch, **server_options):
    a.add("TV_keep", "FROM (2022)")
    a.show("FROM (2022)", favorite=True)
    a.logs.mkdir(exist_ok=True)
    (a.logs / "auditor_state.json").write_text("{}")
    a.set_state("keep_seen", "TV/FROM (2022)", 45)
    series = [{"id": 9, "path": "/tv/FROM (2022)",
               "seasons": [{"seasonNumber": 0, "monitored": False}, {"seasonNumber": 1, "monitored": True},
                           {"seasonNumber": 2, "monitored": True}, {"seasonNumber": 3, "monitored": True}]}]
    return SonarrServer(monkeypatch, series, episode_files({1: 400, 2: 300, 3: 200}), **server_options)


def test_old_seasons_are_unmonitored_first_and_then_their_files_deleted(make_auditor, monkeypatch):
    a = make_auditor(**SONARR_ENV)
    sonarr = prunable_show(a, monkeypatch)
    a.run()

    kinds = [change[0] for change in sonarr.changes]
    assert kinds == ["PUT", "DELETE", "DELETE", "DELETE", "DELETE"]       # unmonitor BEFORE any file is removed
    sent = sonarr.changes[0][2]["seasons"]
    assert {s["seasonNumber"]: s["monitored"] for s in sent} == {0: False, 1: False, 2: False, 3: True}
    deleted_ids = {int(change[1].rsplit("/", 1)[1]) for change in sonarr.changes[1:]}
    assert deleted_ids == {1, 2, 3, 4}                                     # seasons 1 and 2 only
    assert a.actions("prune_seasons")[0]["status"] == "done"


def test_dry_run_sends_sonarr_nothing(make_auditor, monkeypatch):
    a = make_auditor(DRY_RUN="true", **SONARR_ENV)
    sonarr = prunable_show(a, monkeypatch)
    a.run()

    assert sonarr.changes == []
    assert a.actions("prune_seasons")[0]["status"] == "planned"


def test_a_sonarr_failure_while_pruning_is_recorded_not_fatal(make_auditor, monkeypatch):
    a = make_auditor(**SONARR_ENV)
    prunable_show(a, monkeypatch, fail_delete=True)
    a.run()

    failed = a.actions("prune_failed")
    assert len(failed) == 1 and failed[0]["status"] == "failed"
    assert a.actions("prune_seasons") == []
    assert a.actions("run_complete")
