"""Synthetic Settings renders: no production config, request files or actions."""
import os
os.environ.setdefault('WEB_SESSION_SECRET', 'synthetic-settings-secret')
from flask import g, render_template
import web
from config_store import FIELDS, KEYS, SECRETS, BOOLS, DEFAULTS


def render_settings_workspace(scenario='ready'):
    if scenario not in ('ready', 'recovery', 'stale', 'clean', 'review', 'resubmit'):
        raise ValueError('Unknown synthetic Settings scenario')
    values = {key: DEFAULTS.get(key, '') for key in KEYS}
    values.update(JELLYFIN_HOST_URL='https://jellyfin.example.invalid', HOLDING_DAYS='7',
                  SQLITE_DAILY_RUN_TIME='02:00', SQLITE_DAILY_RUN_TIMEZONE='America/Los_Angeles')
    for key in SECRETS:
        values[key] = ''
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
            secrets=SECRETS, bools=BOOLS, help_text=web.FIELD_HELP, preview_mode=True,
            pending_settings=pending, settings_application=application,
            error=None, requested=False, unchanged=False, success=False,
            settings_applied=False, settings_restored=False, settings_apply_busy=False, settings_apply_error=False)


if __name__ == '__main__':
    import sys
    from pathlib import Path
    for scenario in ('ready','recovery','stale','clean','review','resubmit'):
        Path(sys.argv[1]+'.'+scenario+'.html').write_text(render_settings_workspace(scenario))
