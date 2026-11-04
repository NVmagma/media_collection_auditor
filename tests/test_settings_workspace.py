"""Direct JSON settings retain Apply and secret redaction without staging forms."""
from settings_workspace_case import render_settings_workspace

def test_settings_show_only_apply_and_no_staged_recovery_controls():
    page=render_settings_workspace()
    assert 'Apply Requested Settings' in page and 'id="apply-settings-button"' in page
    assert 'name="settings_action" value="apply"' in page
    assert 'name="request_sha256"' not in page and 'I UNDERSTAND' not in page
    assert '/settings/restore' not in page and '/settings/apply' not in page
    assert 'name="JELLYFIN_API_TOKEN" type="password" value=""' in page
    assert 'field-DAILY_RUN_TIMEZONE' in page
