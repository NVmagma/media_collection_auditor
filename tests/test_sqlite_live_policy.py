import pytest
from app.sqlite_live_policy import validate_initial_live_policy,DISABLED


def settings(**changes):
    return dict(AUDITOR_STATE_BACKEND='sqlite',DRY_RUN='false',READ_ONLY_API_SERVICE='false',
        SQLITE_DAILY_RUN_TIME='02:00',SQLITE_DAILY_RUN_TIMEZONE='America/Los_Angeles',
        MAX_ACTIONS_PER_RUN='1',ENABLE_TV='true',**{key:'false' for key in DISABLED})|changes


def test_initial_contract_is_detached_globally_capped_and_not_an_activation():
    values=settings(JELLYFIN_API_TOKEN='private-token')
    policy=validate_initial_live_policy(values);values['MAX_ACTIONS_PER_RUN']='100'
    assert policy.maximum_actions==1 and len(policy.libraries)==2
    assert not hasattr(policy,'production_authorized')
    assert not hasattr(policy,'production_activation')
    assert 'private-token' not in repr(policy)


@pytest.mark.parametrize('key',DISABLED)
@pytest.mark.parametrize('value',['true','yes','',True,None])
def test_unsupported_actions_cannot_enter_initial_contract(key,value):
    with pytest.raises(ValueError,match=key):validate_initial_live_policy(settings(**{key:value}))


@pytest.mark.parametrize('key',['AUDITOR_STATE_BACKEND','DRY_RUN','READ_ONLY_API_SERVICE',*DISABLED])
def test_initial_contract_requires_explicit_values(key):
    values=settings();del values[key]
    with pytest.raises(ValueError,match=key):validate_initial_live_policy(values)


@pytest.mark.parametrize('value',['0','2','10','100','unlimited','1.0'])
def test_initial_global_cap_cannot_be_bypassed(value):
    with pytest.raises(ValueError):validate_initial_live_policy(settings(MAX_ACTIONS_PER_RUN=value))


def test_preview_release_is_not_opened_by_live_settings():
    from app.sqlite_backend_gate import require_sqlite_production_activation
    with pytest.raises(RuntimeError):require_sqlite_production_activation(settings=settings())
