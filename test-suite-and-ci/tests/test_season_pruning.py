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
