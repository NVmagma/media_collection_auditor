"""Opt-in, redacted operational alerts; no media payloads or automatic retries."""
from datetime import datetime, timezone
import hashlib
from threading import Lock
from urllib.parse import urlsplit
import requests

_MESSAGES = {
    'scan_blocked_or_uncertain': 'An auditor scan was blocked or ended with an uncertain result. Review Scans and retained operation state before requesting another attempt.',
    'settings_review_required': 'Auditor settings need review. Open Settings and inspect the application or recovery status. No automatic restoration was performed.',
}
_TARGETS = (('discord','NOTIFY_DISCORD_WEBHOOK_URL'), ('ntfy','NOTIFY_NTFY_URL'), ('webhook','NOTIFY_WEBHOOK_URL'))


def _text(value):
    return value if isinstance(value,str) else ''


def _enabled(value):
    return _text(value).strip().lower() == 'true'


def _destination(value):
    if (not isinstance(value,str) or not 1 <= len(value) <= 4096
            or any(ord(c) <= 32 or ord(c) >= 127 for c in value) or '\\' in value):
        return False
    try:
        parsed=urlsplit(value)
        return (parsed.scheme in ('http','https') and bool(parsed.hostname)
                and parsed.username is None and parsed.password is None
                and not parsed.fragment and '%' not in parsed.netloc
                and (parsed.port is None or 1 <= parsed.port <= 65535))
    except ValueError:
        return False


def _deliver(kind,url,token,payload):
    if not _destination(url) or len(token)>4096 or any(ord(c)<32 or ord(c)>=127 for c in token):
        return False
    options={'json':payload}
    if kind=='discord':
        options={'json':{'content':payload['message'],'allowed_mentions':{'parse':[]}}}
    elif kind=='ntfy':
        headers = {'Title': ('Media Auditor notification test'
                             if payload.get('event') == 'notification_test'
                             else 'Media Auditor needs review')}
        if token:headers['Authorization']='Bearer '+token
        options={'data':payload['message'].encode('utf-8'),'headers':headers}
    # No environment proxies, redirects, redirects carrying credentials or retries.
    with requests.Session() as client:
        client.trust_env=False
        with client.post(url,timeout=(2,3),allow_redirects=False,**options) as response:
            return 200 <= response.status_code < 300


def test_destination(settings, kind):
    """Send one explicitly requested test, independently of alert policy."""
    url = _text(settings.get(dict(_TARGETS)[kind]))
    if not url:
        return False, 'Save a destination for this service before testing.'
    token = _text(settings.get('NOTIFY_NTFY_TOKEN')) if kind == 'ntfy' else ''
    payload = {
        'schema_version': 1,
        'event': 'notification_test',
        'message': 'Media Collection Auditor notification test.',
        'observed_at': datetime.now(timezone.utc).isoformat(),
        'preview': _text(settings.get('DRY_RUN', 'true')).strip().lower() != 'false',
        'media_actions_authorized': False,
    }
    try:
        if _deliver(kind, url, token, payload):
            return True, 'Destination accepted the test. Check your channel or receiver.'
    except Exception:
        pass
    return False, 'Delivery could not be confirmed. Check the saved destination and receiver.'


class OperationalNotifications:
    """At most one attempt per event/destination incident in this process.

    Mark before sending, including failed/uncertain delivery. A successful relevant
    recovery explicitly clears that event. Restart resets this ephemeral state.
    """
    def __init__(self,*,deliver=_deliver):
        self._deliver=deliver
        self._lock=Lock()
        self._attempted={}

    def clear(self,event):
        if event not in _MESSAGES:return
        with self._lock:
            self._attempted={key:None for key in self._attempted if key[0]!=event}

    def emit(self,settings,event):
        try:
            return self._emit(settings,event)
        except Exception:
            # Notification failures never change scan/settings outcomes or leak errors.
            return {'status':'delivery_failed','attempted':0,'delivered':0}

    def _emit(self,settings,event):
        if event not in _MESSAGES:raise ValueError('Known operational event required')
        if not _enabled(settings.get('NOTIFY_OPERATIONAL_FAILURES')):
            return {'status':'disabled','attempted':0,'delivered':0}
        preview=_text(settings.get('DRY_RUN','true')).strip().lower()!='false'
        if preview and not _enabled(settings.get('NOTIFY_ON_DRY_RUN')):
            return {'status':'dry_run_suppressed','attempted':0,'delivered':0}
        payload={'schema_version':1,'event':event,'message':_MESSAGES[event],
                 'observed_at':datetime.now(timezone.utc).isoformat(),
                 'preview':preview,'media_actions_authorized':False}
        attempted=delivered=configured=0
        for kind,key in _TARGETS:
            url=_text(settings.get(key,''))
            if not url:continue
            configured+=1
            token=_text(settings.get('NOTIFY_NTFY_TOKEN','')) if kind=='ntfy' else ''
            identity=(event,hashlib.sha256((kind+'\0'+url+'\0'+token).encode()).digest())
            with self._lock:
                if identity in self._attempted:continue
                if len(self._attempted)>=32:self._attempted.pop(next(iter(self._attempted)))
                self._attempted[identity]=None
            attempted+=1
            try:
                delivered+=bool(self._deliver(kind,url,token,dict(payload)))
            except Exception:
                pass
        status=('no_destinations' if not configured else 'suppressed' if not attempted
                else 'delivered' if delivered==attempted else 'delivery_failed')
        return {'status':status,'attempted':attempted,'delivered':delivered}


NOTIFICATIONS=OperationalNotifications()
