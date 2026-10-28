from unittest.mock import Mock
import pytest
import sys

pytestmark=pytest.mark.skipif(sys.platform!='linux',reason='Linux private preview fixtures')
from tests.test_sqlite_preview_settings_apply_web import page
from app import operational_notifications as notifications


def test_failed_settings_action_uses_only_prior_active_notification_settings(page,monkeypatch):
    client,case,_=page
    case.values.update(NOTIFY_OPERATIONAL_FAILURES='true',NOTIFY_ON_DRY_RUN='true',
        NOTIFY_WEBHOOK_URL='http://fixture.invalid/prior-active')
    send=Mock(return_value=True)
    monkeypatch.setattr(notifications,'NOTIFICATIONS',notifications.OperationalNotifications(deliver=send))
    response=client.post('/settings/apply',data={'request_sha256':'f'*64},headers={'Origin':'http://localhost'})
    assert response.status_code==302 and 'apply_error=1' in response.location
    assert send.call_count==1 and send.call_args.args[1]=='http://fixture.invalid/prior-active'
    assert send.call_args.args[3]['event']=='settings_review_required'
    case.unchanged_tracking()


def test_new_pending_destination_never_receives_failed_apply_alert(page,monkeypatch):
    from tests.test_sqlite_preview_settings_apply_web import edit_form
    from app import sqlite_preview_settings_apply as application
    client,case,_=page
    case.values.update(NOTIFY_OPERATIONAL_FAILURES='false',NOTIFY_ON_DRY_RUN='false')
    send=Mock(return_value=True)
    monkeypatch.setattr(notifications,'NOTIFICATIONS',notifications.OperationalNotifications(deliver=send))
    monkeypatch.setattr(application,'apply_requested_settings',Mock(side_effect=RuntimeError('private')))
    response=client.post('/settings',data=edit_form(case,NOTIFY_OPERATIONAL_FAILURES='true',
        NOTIFY_ON_DRY_RUN='true',NOTIFY_WEBHOOK_URL='http://fixture.invalid/new-pending'),headers={'Origin':'http://localhost'})
    assert response.status_code==302 and 'apply_error=1' in response.location
    send.assert_not_called()
    assert case.saved.read_bytes()==case.original
    case.unchanged_tracking()
