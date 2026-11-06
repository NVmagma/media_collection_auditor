import pytest

from app.tv_season_policy import SeasonPlan, plan_seasons


def test_tag_stages_older_regular_seasons_even_with_numbering_gaps():
    assert plan_seasons(tags=['One-Season'], active=[0, 1, 3, 8], leaving_soon=[], verified=True) == (
        SeasonPlan(latest=8, stage=(1, 3))
    )


@pytest.mark.parametrize('tag', ['keep-all', 'KEEP-ALL-SEASONS', 'keep-forever', 'custom-keep-all'])
def test_protection_overrides_one_season_and_restores_older_seasons(tag):
    assert plan_seasons(tags=['one-season', tag], active=[3, 4], leaving_soon=[1, 2],
                        verified=True, keep_all_tag='custom-keep-all') == (
        SeasonPlan(latest=4, restore=(1, 2))
    )


def test_latest_season_in_leaving_soon_is_eligible_for_restore():
    assert plan_seasons(tags=['one-season'], active=[1], leaving_soon=[3], verified=True) == (
        SeasonPlan(latest=3, stage=(1,), restore=(3,))
    )


def test_absent_tag_and_unverified_or_split_inventory_do_not_plan_changes():
    assert plan_seasons(tags=[], active=[1, 2], leaving_soon=[], verified=True) == SeasonPlan(latest=2)
    assert plan_seasons(tags=['one-season'], active=[1, 2], leaving_soon=[], verified=False).blocked
    assert plan_seasons(tags=['one-season'], active=[1, 2], leaving_soon=[1], verified=True).blocked
