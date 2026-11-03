from unittest.mock import Mock
import pytest
from tests.test_integration_api import api, AUTH
import web
from app import arr_import_service as service


@pytest.fixture
def page(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(web, 'current_user', lambda: {'admin': True, 'name': 'Synthetic admin'})
    response = client.get('/arr-imports')
    assert response.status_code == 200
    with client.session_transaction() as session: csrf = session['arr_import_csrf']
    return client, csrf


@pytest.mark.parametrize('endpoint', ['/arr-imports', '/api/arr-import/options', '/api/arr-import/lookup'])
def test_integration_token_never_grants_import_browser_access(api, monkeypatch, endpoint):
    client, _ = api
    monkeypatch.setattr(web, 'current_user', lambda: None)
    assert client.get(endpoint, headers=AUTH).status_code in (302, 401)
    monkeypatch.setattr(web, 'current_user', lambda: {'admin': False, 'name': 'Reader'})
    assert client.get(endpoint, headers=AUTH).status_code == 403


def test_csrf_and_origin_block_before_any_import_call(page, monkeypatch):
    client, csrf = page
    create = Mock(side_effect=AssertionError('No external call'))
    monkeypatch.setattr(service, 'apply', create)
    for data, origin in [({'csrf': csrf}, None), ({'csrf': 'wrong'}, 'http://localhost'),
                         ({'csrf': csrf}, 'http://foreign.invalid')]:
        headers = {'Origin': origin} if origin else {}
        assert client.post('/api/arr-import/apply', json=data, headers=headers).status_code == 403
    create.assert_not_called()


def test_review_apply_is_exact_expiring_single_use_browser_consent(page, monkeypatch):
    client, csrf = page
    chosen = dict(library='TV', folder='Existing', provider_id=100, quality_profile_id=2)
    prepare = Mock(return_value={'review_fingerprint': 'a'*64, 'read_only': True})
    create = Mock(return_value={'status': 'existing_media_import_verified'})
    monkeypatch.setattr(service, 'review', prepare); monkeypatch.setattr(service, 'apply', create)
    headers = {'Origin': 'http://localhost'}
    assert client.post('/api/arr-import/apply', json={'csrf': csrf, 'review_fingerprint': 'a'*64}, headers=headers).status_code == 409
    assert client.post('/api/arr-import/review', json={'csrf': csrf, **chosen, 'monitored': True}, headers=headers).status_code == 400
    response = client.post('/api/arr-import/review', json={'csrf': csrf, **chosen}, headers=headers)
    assert response.status_code == 200 and response.headers['Cache-Control'] == 'no-store'
    response = client.post('/api/arr-import/apply', json={'csrf': csrf, 'review_fingerprint': 'a'*64}, headers=headers)
    assert response.status_code == 200
    create.assert_called_once_with(selection=chosen, expected_fingerprint='a'*64)
    assert client.post('/api/arr-import/apply', json={'csrf': csrf, 'review_fingerprint': 'a'*64}, headers=headers).status_code == 409


def test_expired_or_failed_attempt_is_not_silently_retried(page, monkeypatch):
    client, csrf = page
    create = Mock(side_effect=RuntimeError('private-token-response-url'))
    monkeypatch.setattr(service, 'apply', create)
    with client.session_transaction() as session:
        session['arr_import_review'] = {'selection': {}, 'fingerprint': 'a'*64, 'at': 0}
    headers = {'Origin':'http://localhost'}
    body = {'csrf':csrf, 'review_fingerprint':'a'*64}
    assert client.post('/api/arr-import/apply', json=body, headers=headers).status_code == 409
    create.assert_not_called()
    import time
    with client.session_transaction() as session:
        session['arr_import_review'] = {'selection': {}, 'fingerprint': 'a'*64, 'at': time.time()}
    response = client.post('/api/arr-import/apply', json=body, headers=headers)
    assert response.status_code == 409 and 'private-token' not in response.text
    assert response.json['automatic_retry'] is False
    assert client.post('/api/arr-import/apply', json=body, headers=headers).status_code == 409
    create.assert_called_once()


def test_explicit_recovery_uses_separate_review_and_consent(page, monkeypatch):
    client, csrf = page
    recover = Mock(side_effect=[{'review_fingerprint': 'b'*64, 'status': 'import_outcome_matches'},
                               {'status': 'import_intent_reconciled'}])
    monkeypatch.setattr(service, 'recover', recover)
    headers = {'Origin':'http://localhost'}
    assert client.post('/api/arr-import/recovery-review', json={'csrf':csrf}, headers=headers).status_code == 200
    assert client.post('/api/arr-import/recovery-apply', json={'csrf':csrf,'review_fingerprint':'b'*64}, headers=headers).status_code == 200
    assert recover.call_args.kwargs == {'expected_fingerprint':'b'*64}
    assert client.post('/api/arr-import/recovery-apply', json={'csrf':csrf,'review_fingerprint':'b'*64}, headers=headers).status_code == 409


def test_import_page_does_not_render_private_configuration(page):
    client, _ = page
    response = client.get('/arr-imports')
    assert 'Imports start unmonitored' in response.text
    assert 'download searches disabled' in response.text
    assert 'API_KEY' not in response.text
    assert response.headers['Cache-Control'] == 'no-store'
