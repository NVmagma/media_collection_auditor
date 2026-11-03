"""Best-effort library refresh after a completed live batch; never replay moves."""
from urllib.request import Request
from urllib.error import HTTPError
from app.sqlite_scheduled_transport import ScheduledJellyfinGET


def refresh_after_moves(*, settings, completed, maximum_seconds=10):
    """Honor the existing opt-in setting; acknowledgment is not scan completion.

    Called once by the locked live worker after move and Arr completion. No
    retries, redirects, response payload logging or persistent state changes.
    """
    status = 'not_requested'
    if (settings.get('JELLYFIN_REFRESH_AFTER_AUDIT', 'false').strip().lower() != 'true'
            or settings.get('DRY_RUN', 'true').strip().lower() != 'false'
            or completed is not True):
        return {'status': status, 'scan_completion_verified': False}
    try:
        if maximum_seconds <= 0:
            raise RuntimeError('Refresh deadline unavailable')
        # Reuse the scheduled URL/token validation and no-proxy/no-redirect opener.
        transport = ScheduledJellyfinGET(base_url=settings.get('JELLYFIN_HOST_URL'),
            token=settings.get('JELLYFIN_API_TOKEN'), timeout_seconds=min(10, maximum_seconds))
        request = Request(transport._base + '/Library/Refresh', data=b'', method='POST',
            headers={'X-Emby-Token': transport._token,
                     'Authorization': 'MediaBrowser Token="' + transport._token + '"'})
        with transport._opener.open(request, timeout=min(10, maximum_seconds)) as response:
            if response.status not in (200, 202, 204):
                raise RuntimeError('Refresh response rejected')
        status = 'requested'
        print('[JELLYFIN REFRESH] Library scan requested; completion not verified.', flush=True)
    except Exception as error:
        if isinstance(error, HTTPError):
            error.close()
        status = 'failed_or_uncertain'
        print('[JELLYFIN REFRESH] Request failed or uncertain; completed moves retained; no automatic retry.', flush=True)
    return {'status': status, 'scan_completion_verified': False}
