"""Synthetic Settings renders: no production config, request files or actions."""
import os
os.environ.setdefault('WEB_SESSION_SECRET', 'synthetic-settings-secret')
from flask import g, render_template
import web
from config_store import LIVE_CANARY_LOCKED_KEYS as LOCKED
from config_store import FIELDS, KEYS, SECRETS, BOOLS, DEFAULTS


def render_settings_workspace(scenario='ready'):
    if scenario not in ('ready', 'recovery', 'stale', 'clean', 'review', 'resubmit', 'live'):
        raise ValueError('Unknown synthetic Settings scenario')
    values = {key: DEFAULTS.get(key, '') for key in KEYS}
    values.update(JELLYFIN_HOST_URL='https://jellyfin.example.invalid', HOLDING_DAYS='7',
                  SQLITE_DAILY_RUN_TIME='02:00', SQLITE_DAILY_RUN_TIMEZONE='America/Los_Angeles')
    for key in SECRETS:
        values[key] = ''
    if scenario=='live':values.update(DRY_RUN='false',MAX_ACTIONS_PER_RUN='1')
    pending = {'status':'requested', 'changed_keys':['ENABLE_TV','HOLDING_DAYS','JELLYFIN_API_TOKEN']}
    application = {'status':'ready', 'request_sha256':'a'*64}
    if scenario == 'recovery':
        application['status'] = 'recovery_required'
    elif scenario == 'stale':
        pending = {'status':'stale', 'changed_keys':[]}
        application = {'status':'review_required'}
    elif scenario == 'clean':
        pending = {'status':'none', 'changed_keys':[]}
        application = {'status':'none'}
    elif scenario == 'review':
        pending = {'status':'review_required', 'changed_keys':[]}
        application = {'status':'review_required'}
    elif scenario == 'resubmit':
        application = {'status':'resubmit_required'}
    with web.app.test_request_context('/settings'):
        g.user = {'name':'Synthetic administrator', 'admin':True}
        return render_template('settings.html', groups=FIELDS, values=values, sources={key:'Default' for key in KEYS},
            secrets=SECRETS, bools=BOOLS, help_text=web.FIELD_HELP, preview_mode=True,live_mode=scenario=='live',
            locked_settings=LOCKED if scenario=='live' else (),
            pending_settings=pending, settings_application=application,
            error=None, requested=False, unchanged=False, success=False,
            settings_applied=False, settings_restored=False, settings_apply_busy=False, settings_apply_error=False)


def render_integration_workspace():
    """Render synthetic readiness without inspecting host config or tracking."""
    with web.app.test_request_context('/integrations'):
        g.user = {'name':'Synthetic administrator', 'admin':True}
        return render_template('integrations.html', token_ready=True, readiness={
            'tracking_available':True, 'storage_authority':'sqlite',
            'binding_status':'verified', 'title_details_enabled':True,
            'poster_lookup_enabled':True, 'coverage_enabled':True, 'backup_selection_configured':False, 'coordinator_scope':'current_process'})


if __name__ == '__main__':
    import sys
    from pathlib import Path
    for scenario in ('ready','recovery','stale','clean','review','resubmit','live'):
        Path(sys.argv[1]+'.'+scenario+'.html').write_text(render_settings_workspace(scenario))
