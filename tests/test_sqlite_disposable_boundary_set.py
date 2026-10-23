import pytest
from app.sqlite_disposable_boundary_set import compose_disposable_boundaries


def test_all_domains_are_required_and_revisited_in_reverse_order():
    calls = []
    def check(name):
        return lambda: calls.append(name)
    verify = compose_disposable_boundaries(docker=check('docker'), nfs=check('nfs'),
        host_storage=check('host_storage'), timer=lambda:0)
    assert verify() is None
    assert calls == ['docker','nfs','host_storage','host_storage','nfs','docker']


@pytest.mark.parametrize('domain', ['docker','nfs','host_storage'])
def test_missing_adapter_rejected_before_observations(domain):
    checks = {name: lambda:pytest.fail('No observations') for name in ('docker','nfs','host_storage')}
    checks[domain] = None
    with pytest.raises(ValueError, match='All three'):
        compose_disposable_boundaries(**checks)


@pytest.mark.parametrize('domain', ['docker','nfs','host_storage'])
@pytest.mark.parametrize('outcome', [True,False,{'authorized':True},'error'])
def test_denial_or_authority_receipt_latches_failure_without_recovery(domain,outcome):
    calls=[]
    broken=True
    def provider(name):
        def check():
            calls.append(name)
            if name == domain and broken:
                if outcome == 'error': raise RuntimeError('private credential detail')
                return outcome
        return check
    verify=compose_disposable_boundaries(**{name:provider(name) for name in ('docker','nfs','host_storage')})
    with pytest.raises(RuntimeError,match=domain) as caught:
        verify()
    assert 'private credential' not in str(caught.value)
    before=list(calls); broken=False
    with pytest.raises(RuntimeError,match='retained review'):
        verify()
    assert calls == before


@pytest.mark.parametrize('clock', [[0,6],[1,0],[float('nan')],[True]])
def test_clock_uncertainty_blocks(clock):
    values=iter(clock)
    verify=compose_disposable_boundaries(docker=lambda:None,nfs=lambda:None,
        host_storage=lambda:None,timer=lambda:next(values))
    with pytest.raises(RuntimeError,match='clock unavailable|window expired'):
        verify()


def test_caught_recursive_failure_still_blocks_outer_check():
    def nested():
        try: verify()
        except RuntimeError: pass
    verify=compose_disposable_boundaries(docker=nested,nfs=lambda:None,host_storage=lambda:None)
    with pytest.raises(RuntimeError,match='interrupted'):
        verify()
    with pytest.raises(RuntimeError,match='retained review'):
        verify()


def test_changed_domain_on_second_pass_is_not_cached_as_success():
    calls=0
    def nfs():
        nonlocal calls
        calls+=1
        if calls==2: raise RuntimeError('state changed')
    verify=compose_disposable_boundaries(docker=lambda:None,nfs=nfs,host_storage=lambda:None)
    with pytest.raises(RuntimeError,match='nfs'):
        verify()
    assert calls==2


def test_interruption_latches_failure():
    def interrupt(): raise KeyboardInterrupt()
    verify=compose_disposable_boundaries(docker=interrupt,nfs=lambda:None,host_storage=lambda:None)
    with pytest.raises(KeyboardInterrupt): verify()
    with pytest.raises(RuntimeError,match='retained review'): verify()
