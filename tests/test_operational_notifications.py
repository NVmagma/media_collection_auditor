"""Send alerts only when enabled and keep private details out of them."""
import json
from unittest.mock import Mock
import pytest
from test_integration_api import api
from app.operational_notifications import OperationalNotifications,_deliver


def settings(**values):
    return {'NOTIFY_OPERATIONAL_FAILURES':'true','NOTIFY_ON_DRY_RUN':'true','DRY_RUN':'true',
            'NOTIFY_WEBHOOK_URL':'http://fixture.invalid/private-hook',
            'JELLYFIN_API_TOKEN':'private-secret','private_error':'private-secret',**values}


def test_disabled_and_dry_run_suppressed_never_contact_targets():
    send=Mock(side_effect=AssertionError('No transport'))
    alerts=OperationalNotifications(deliver=send)
    assert alerts.emit(settings(NOTIFY_OPERATIONAL_FAILURES='false'),'scan_blocked_or_uncertain')['status']=='disabled'
    assert alerts.emit(settings(NOTIFY_ON_DRY_RUN='false'),'scan_blocked_or_uncertain')['status']=='dry_run_suppressed'
    assert alerts.emit(settings(NOTIFY_WEBHOOK_URL=''),'scan_blocked_or_uncertain')['status']=='no_destinations'
    send.assert_not_called()


def test_allowlisted_payload_deduplication_and_recovery():
    sent=[]
    alerts=OperationalNotifications(deliver=lambda *args:sent.append(args) or True)
    source=settings()
    result=alerts.emit(source,'scan_blocked_or_uncertain')
    assert result=={'status':'delivered','attempted':1,'delivered':1}
    assert 'private-secret' not in json.dumps(sent[0][3])
    assert 'private-hook' not in json.dumps(sent[0][3])
    assert sent[0][3]['media_actions_authorized'] is False
    assert alerts.emit(source,'scan_blocked_or_uncertain')['status']=='suppressed'
    alerts.clear('scan_blocked_or_uncertain')
    assert alerts.emit(source,'scan_blocked_or_uncertain')['attempted']==1
    assert OperationalNotifications(deliver=lambda *a:True).emit(source,'scan_blocked_or_uncertain')['attempted']==1


def test_failed_delivery_not_retried_and_other_targets_continue():
    calls=[]
    def deliver(kind,*args):
        calls.append(kind)
        if kind=='discord':raise RuntimeError('private-error')
        return True
    alerts=OperationalNotifications(deliver=deliver)
    source=settings(NOTIFY_DISCORD_WEBHOOK_URL='https://fixture.invalid/private-discord')
    result=alerts.emit(source,'settings_review_required')
    assert result=={'status':'delivery_failed','attempted':2,'delivered':1}
    assert alerts.emit(source,'settings_review_required')['status']=='suppressed'
    assert calls==['discord','webhook']
    assert 'private' not in json.dumps(result)


@pytest.mark.parametrize('url',['file:///tmp/secret','http://user:password@localhost/x','http://localhost/x#secret','http://localhost:99999','http://localhost/\nprivate','http://localhost\\private'])
def test_invalid_destinations_never_contact_network(url,monkeypatch):
    monkeypatch.setattr('requests.Session',Mock(side_effect=AssertionError('No session')))
    assert _deliver('webhook',url,'',{'message':'fixed'}) is False


def test_ntfy_header_injection_refused(monkeypatch):
    monkeypatch.setattr('requests.Session',Mock(side_effect=AssertionError('No session')))
    assert _deliver('ntfy','https://fixture.invalid/topic','bad\r\nheader',{'message':'fixed'}) is False


def test_transport_no_proxy_redirect_or_retry_and_secret_free_body(monkeypatch):
    client=Mock();client.__enter__=Mock(return_value=client);client.__exit__=Mock(return_value=False)
    response=Mock(status_code=302);response.__enter__=Mock(return_value=response);response.__exit__=Mock(return_value=False)
    client.post.return_value=response
    monkeypatch.setattr('requests.Session',lambda:client)
    assert _deliver('discord','https://fixture.invalid/hook','',{'message':'fixed'}) is False
    assert client.trust_env is False
    assert client.post.call_args.kwargs['allow_redirects'] is False
    assert client.post.call_args.kwargs['timeout']==(2,3)
    assert client.post.call_args.kwargs['json']['allowed_mentions']=={'parse':[]}
    client.post.assert_called_once()


def test_admin_notification_request_uses_saved_destination(api, monkeypatch):
    import web
    from app import operational_notifications, json_worker_service

    client, _ = api
    send = Mock(return_value=True)
    monkeypatch.setattr(operational_notifications, '_deliver', send)
    snapshot = Mock(return_value=settings(NOTIFY_OPERATIONAL_FAILURES='false'))
    monkeypatch.setattr(json_worker_service, 'settings_snapshot', snapshot)
    path = '/api/test-notification/webhook'
    headers = {'Origin': 'http://localhost', 'X-Auditor-Action': 'test-notification'}
    assert client.post(path, headers=headers).status_code == 401
    monkeypatch.setattr(web, 'current_user', lambda: {'admin': False})
    assert client.post(path, headers=headers).status_code == 403
    monkeypatch.setattr(web, 'current_user', lambda: {'admin': True})
    assert client.post(path, headers={'Origin': 'http://localhost'}).status_code == 403
    assert client.post(path, headers={**headers, 'Origin': 'http://other.invalid'}).status_code == 403
    snapshot.assert_not_called()
    send.assert_not_called()

    response = client.post(path, headers=headers, json={'url': 'http://other.invalid'})
    assert response.status_code == 200 and response.json['ok']
    send.assert_called_once()
    kind, url, token, payload = send.call_args.args
    assert (kind, url, token) == ('webhook', 'http://fixture.invalid/private-hook', '')
    assert payload['event'] == 'notification_test'
    assert payload['media_actions_authorized'] is False
    assert 'private-' not in json.dumps(payload)
    assert 'private-' not in response.text

    send.side_effect = RuntimeError('private-transport-error')
    failure = client.post(path, headers=headers)
    assert failure.json['ok'] is False
    assert 'private-' not in failure.text
    assert send.call_count == 2
