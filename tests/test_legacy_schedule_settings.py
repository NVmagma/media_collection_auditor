"""Old field aliases remain readable without restoring an alternate backend."""
from app.legacy_settings import normalize_schedule,SCHEDULE_ALIASES
from app.config_store import validate

def test_old_schedule_and_zone_are_preserved_without_writing_input():
    old=dict(zip(SCHEDULE_ALIASES,('05:15','America/Los_Angeles')))
    before=dict(old); current=normalize_schedule(old)
    assert current=={'DAILY_RUN_TIME':'05:15','DAILY_RUN_TIMEZONE':'America/Los_Angeles'}
    assert old==before
    for key,value in current.items():assert validate(key,value)==value

def test_canonical_override_wins_and_unrelated_fields_are_retained():
    old=next(iter(SCHEDULE_ALIASES))
    assert normalize_schedule({old:'02:00','DAILY_RUN_TIME':'03:10','extension':42})=={'DAILY_RUN_TIME':'03:10','extension':42}
