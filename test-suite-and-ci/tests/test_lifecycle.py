"""Movies and TV: Transient -> Holding -> Removal -> deleted, plus favorites, rescue, safety limits."""
import json

import pytest


def build_library(a):
    """A small library with one title in every interesting situation."""
    a.add("Movies", "Favorite (2000)")
    a.add("Movies", "Hated (2001)")
    a.add("Movies", "Undecided (2002)")
    a.add("Movies", "Fresh (2026)")
    a.add("Movies_hold", "Rescued (1999)")
    a.add("Movies_hold", "Expired (1998)")
    a.add("Movies_hold", "Still Holding (1997)")
    a.add("Movies_removal", "Overdue (1996)")
    a.add("Movies_removal", "Recent (1995)")
    a.movie("Favorite (2000)", favorite=True)
    a.movie("Hated (2001)", disliked=True)
    a.movie("Undecided (2002)")
    a.movie("Fresh (2026)")
    a.movie("Rescued (1999)", favorite=True)
    a.movie("Expired (1998)")
    a.movie("Still Holding (1997)")


def seed_state(a):
    a.logs.mkdir()
    (a.logs / "auditor_state.json").write_text(json.dumps({"first_seen": {}, "queued": {}, "in_removal": {}}))
    a.set_state("first_seen", "Undecided (2002)", 40)     # older than the 30-day wait
    a.set_state("first_seen", "Fresh (2026)", 3)          # still inside the wait
    a.set_state("queued", "Rescued (1999)", 2)
    a.set_state("queued", "Expired (1998)", 9)            # past HOLDING_DAYS (7)
    a.set_state("queued", "Still Holding (1997)", 2)
    a.set_state("in_removal", "Overdue (1996)", 9)        # past REMOVAL_DAYS (7)
    a.set_state("in_removal", "Recent (1995)", 2)


def test_movie_lifecycle(make_auditor):
    a = make_auditor()
    build_library(a)
    seed_state(a)
    a.run()

    assert a.where("Favorite (2000)") == "Movies_keep"          # favorited -> Keep
    assert a.where("Hated (2001)") == "Movies_hold"             # not-at-all tag -> Holding right away
    assert a.where("Undecided (2002)") == "Movies_hold"         # no favorite after 30 days -> Holding
    assert a.where("Fresh (2026)") == "Movies"                  # still waiting
    assert a.where("Rescued (1999)") == "Movies_keep"           # favorited while in Holding -> Keep
    assert a.where("Expired (1998)") == "Movies_removal"        # Holding time ran out -> Removal
    assert a.where("Still Holding (1997)") == "Movies_hold"     # still inside HOLDING_DAYS
    assert a.where("Overdue (1996)") == "GONE"                  # Removal time ran out -> deleted
    assert a.where("Recent (1995)") == "Movies_removal"         # still inside REMOVAL_DAYS


def test_actions_are_logged(make_auditor):
    a = make_auditor()
    build_library(a)
    seed_state(a)
    a.run()

    assert {r["folder"] for r in a.actions("hold")} == {"Hated (2001)", "Undecided (2002)"}
    assert [r["folder"] for r in a.actions("rescue")] == ["Rescued (1999)"]
    assert [r["folder"] for r in a.actions("to_removal")] == ["Expired (1998)"]
    assert [r["folder"] for r in a.actions("delete")] == ["Overdue (1996)"]
    assert len(a.actions("run_complete")) == 1


def test_dry_run_changes_nothing(make_auditor):
    a = make_auditor(DRY_RUN="true")
    build_library(a)
    seed_state(a)
    before = {name: a.where(name) for name in
              ["Favorite (2000)", "Hated (2001)", "Undecided (2002)", "Expired (1998)", "Overdue (1996)"]}
    a.run()
    after = {name: a.where(name) for name in before}

    assert after == before
    assert all(r["dry_run"] for r in a.actions())              # every log line is flagged as a dry run


def test_grace_period_for_existing_backlog(make_auditor):
    """A folder that is years old on disk still gets a full waiting period from the first run."""
    a = make_auditor()
    a.add("Movies", "Ancient (1980)", age_days=5000)
    a.movie("Ancient (1980)")
    a.run()

    assert a.where("Ancient (1980)") == "Movies"
    assert "Ancient (1980)" in a.state()["first_seen"]


def test_action_cap_limits_moves_into_holding(make_auditor):
    a = make_auditor(MAX_ACTIONS_PER_RUN=3)
    a.logs.mkdir()
    (a.logs / "auditor_state.json").write_text(json.dumps({"first_seen": {}}))
    for i in range(8):
        name = f"Movie {i} (2000)"
        a.add("Movies", name)
        a.movie(name)
        a.set_state("first_seen", name, 40)
    a.run()

    moved = [i for i in range(8) if a.where(f"Movie {i} (2000)") == "Movies_hold"]
    assert len(moved) == 3
    assert len(a.actions("cap_skipped")) == 5


def test_favorites_are_not_limited_by_the_cap(make_auditor):
    a = make_auditor(MAX_ACTIONS_PER_RUN=1)
    for i in range(4):
        name = f"Loved {i} (2000)"
        a.add("Movies", name)
        a.movie(name, favorite=True)
    a.run()

    assert all(a.where(f"Loved {i} (2000)") == "Movies_keep" for i in range(4))


def test_unknown_to_jellyfin_is_left_alone(make_auditor):
    a = make_auditor()
    a.add("Movies", "Not Scanned (2020)")
    a.run()

    assert a.where("Not Scanned (2020)") == "Movies"


def test_existing_destination_is_never_overwritten(make_auditor):
    a = make_auditor()
    a.add("Movies", "Twin (2000)")
    a.add("Movies_keep", "Twin (2000)")
    a.movie("Twin (2000)", favorite=True)
    a.run()

    assert (a.media / "Movies" / "Twin (2000)").is_dir()        # source untouched
    assert (a.media / "Movies_keep" / "Twin (2000)" / "video.mkv").exists()


def test_old_state_files_without_new_sections_still_load(make_auditor):
    """State saved by an earlier version (no in_removal / keep_seen) must keep working."""
    a = make_auditor()
    a.logs.mkdir()
    (a.logs / "auditor_state.json").write_text(json.dumps({"first_seen": {"Old (1999)": "2020-01-01T00:00:00"}, "queued": {}}))
    a.add("Movies", "Old (1999)")
    a.movie("Old (1999)")
    a.run()

    assert a.where("Old (1999)") == "Movies_hold"               # clock from the old state file is honored


# ---------------- TV ----------------

def test_tv_uses_its_own_folders_and_longer_wait(make_auditor):
    a = make_auditor(ENABLE_TV="true")
    for show in ("Loved Show", "Hated Show", "Waiting Show", "Overdue Show"):
        a.add("TV", show, age_days=200)                          # old episodes: the clock isn't reset
        a.show(show)
    a.show("Loved Show", favorite=True)
    a.show("Hated Show", disliked=True)
    a.logs.mkdir()
    (a.logs / "auditor_state.json").write_text(json.dumps({"first_seen": {}}))
    a.set_state("first_seen", "TV/Waiting Show", 45)             # 60-day wait for TV: still waiting
    a.set_state("first_seen", "TV/Overdue Show", 70)
    a.run()

    assert a.where("Loved Show") == "TV_keep"
    assert a.where("Hated Show") == "TV_hold"
    assert a.where("Waiting Show") == "TV"
    assert a.where("Overdue Show") == "TV_hold"


def test_airing_show_restarts_its_clock(make_auditor):
    a = make_auditor(ENABLE_TV="true")
    a.add("TV", "Airing Show")                                   # fresh files = a recent episode
    a.add("TV", "Finished Show", age_days=200)
    a.show("Airing Show")
    a.show("Finished Show")
    a.logs.mkdir()
    (a.logs / "auditor_state.json").write_text(json.dumps({"first_seen": {}}))
    a.set_state("first_seen", "TV/Airing Show", 90)
    a.set_state("first_seen", "TV/Finished Show", 90)
    a.run()

    assert a.where("Airing Show") == "TV"
    assert a.where("Finished Show") == "TV_hold"


def test_strict_tv_clock_when_reset_is_disabled(make_auditor):
    a = make_auditor(ENABLE_TV="true", TV_NEW_EPISODES_RESET_CLOCK="false")
    a.add("TV", "Airing Show")
    a.show("Airing Show")
    a.logs.mkdir()
    (a.logs / "auditor_state.json").write_text(json.dumps({"first_seen": {}}))
    a.set_state("first_seen", "TV/Airing Show", 90)
    a.run()

    assert a.where("Airing Show") == "TV_hold"


def test_movie_and_show_with_same_name_do_not_collide(make_auditor):
    a = make_auditor(ENABLE_TV="true")
    a.add("Movies", "Twin (2000)")
    a.add("TV", "Twin (2000)", age_days=200)
    a.movie("Twin (2000)")
    a.show("Twin (2000)")
    a.run()
    state = a.state()["first_seen"]

    assert "Twin (2000)" in state and "TV/Twin (2000)" in state


def test_movies_only_by_default(make_auditor):
    a = make_auditor()                                           # ENABLE_TV defaults to false
    a.add("TV", "Some Show")
    a.show("Some Show", favorite=True)
    a.run()

    assert a.where("Some Show") == "TV"


def test_custom_folder_names_and_timers(make_auditor, tmp_path):
    a = make_auditor(
        RADARR_TRANSIENT_PATH=tmp_path / "media" / "Inbox",
        RADARR_HOLDING_PATH=tmp_path / "media" / "LeavingSoon",
        RADARR_KEEP_PATH=tmp_path / "media" / "Forever",
        RADARR_REMOVAL_PATH=tmp_path / "media" / "Trash",
        MOVIE_WAIT_DAYS=5,
    )
    a.add("Inbox", "Slow (2000)")
    a.add("Inbox", "Loved (2000)")
    a.movie("Slow (2000)")
    a.movie("Loved (2000)", favorite=True)
    a.logs.mkdir()
    (a.logs / "auditor_state.json").write_text(json.dumps({"first_seen": {}}))
    a.set_state("first_seen", "Slow (2000)", 6)
    a.run()

    assert a.where("Slow (2000)") == "LeavingSoon"
    assert a.where("Loved (2000)") == "Forever"


# ---------------- exact day boundaries ----------------

@pytest.mark.parametrize("days, expected", [(29, "Movies"), (30, "Movies_hold")])
def test_transient_wait_boundary(make_auditor, days, expected):
    a = make_auditor()
    a.add("Movies", "Edge (2000)")
    a.movie("Edge (2000)")
    a.logs.mkdir()
    (a.logs / "auditor_state.json").write_text(json.dumps({"first_seen": {}}))
    a.set_state("first_seen", "Edge (2000)", days)
    a.run()

    assert a.where("Edge (2000)") == expected


@pytest.mark.parametrize("days, expected", [(6, "Movies_hold"), (7, "Movies_removal")])
def test_holding_time_boundary(make_auditor, days, expected):
    a = make_auditor()
    a.add("Movies_hold", "Edge (2000)")
    a.movie("Edge (2000)")
    a.logs.mkdir()
    (a.logs / "auditor_state.json").write_text(json.dumps({"queued": {}}))
    a.set_state("queued", "Edge (2000)", days)
    a.run()

    assert a.where("Edge (2000)") == expected


@pytest.mark.parametrize("days, expected", [(6, "Movies_removal"), (7, "GONE")])
def test_removal_time_boundary(make_auditor, days, expected):
    a = make_auditor()
    a.add("Movies_removal", "Edge (2000)")
    a.logs.mkdir()
    (a.logs / "auditor_state.json").write_text(json.dumps({"in_removal": {}}))
    a.set_state("in_removal", "Edge (2000)", days)
    a.run()

    assert a.where("Edge (2000)") == expected


def test_dry_run_deletes_nothing_even_when_overdue(make_auditor):
    a = make_auditor(DRY_RUN="true")
    a.add("Movies_removal", "Overdue (1996)")
    a.logs.mkdir()
    (a.logs / "auditor_state.json").write_text(json.dumps({"in_removal": {}}))
    a.set_state("in_removal", "Overdue (1996)", 30)
    a.run()

    assert (a.media / "Movies_removal" / "Overdue (1996)" / "video.mkv").exists()
