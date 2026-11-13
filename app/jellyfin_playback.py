"""Defer media actions when Jellyfin reports playback or cannot verify it."""
from pathlib import PurePosixPath
import unicodedata

from app.filesystem_paths import _canonical
from app.jellyfin_transport import ScheduledJellyfinGET, ScheduledTransportError


class PlaybackDeferred(RuntimeError):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def _fold(value):
    return unicodedata.normalize('NFC', value).casefold()


def check_active_playback(settings, title, source_path, season=None):
    """Read live sessions without storing viewer, device, or playback data."""
    try:
        fetch = ScheduledJellyfinGET(base_url=settings.get('JELLYFIN_HOST_URL', ''),
                                     token=settings.get('JELLYFIN_API_TOKEN', ''))
        sessions = fetch('/Sessions', None)
        if not isinstance(sessions, list):
            raise ValueError('Expected session list')
        source = PurePosixPath(_fold(source_path))
        for session in sessions:
            if not isinstance(session, dict) or not isinstance(session.get('Id'), str) or not session['Id']:
                raise ValueError('Invalid session')
            item = session.get('NowPlayingItem')
            if item is None:
                continue
            if not isinstance(item, dict):
                raise ValueError('Invalid playing item')
            # Audio-only playback is outside the managed movie and TV actions.
            if item.get('MediaType') == 'Audio':
                continue
            path = PurePosixPath(_fold(_canonical(item.get('Path'))))
            if source in path.parents:
                raise PlaybackDeferred('active_playback')
            # The Jellyfin and Auditor mounts can have different root prefixes.
            if _fold(title) in path.parent.parts:
                if season is None or item.get('ParentIndexNumber') == season:
                    raise PlaybackDeferred('active_playback')
                if type(item.get('ParentIndexNumber')) is not int:
                    raise ValueError('Missing playback season')
            # A different media-source ID can mean Jellyfin supplied the default
            # version's path while the viewer is playing another version.
            state = session.get('PlayState')
            if state is not None:
                if not isinstance(state, dict):
                    raise ValueError('Invalid playback state')
                source_id = state.get('MediaSourceId')
                item_id = item.get('Id')
                if source_id and (not isinstance(source_id, str) or not isinstance(item_id, str)
                                  or source_id.replace('-', '').lower() != item_id.replace('-', '').lower()):
                    raise ValueError('Selected playback source is unresolved')
    except (ScheduledTransportError, ValueError):
        raise PlaybackDeferred('playback_unavailable') from None
