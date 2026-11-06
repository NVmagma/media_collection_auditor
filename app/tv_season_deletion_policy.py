"""Separate saved consent for deleting expired staged TV seasons."""

FLAG = 'ALLOW_TV_SEASON_DELETE'
CONSENT_KEY = 'TV_SEASON_DELETION_CONSENT'
CONSENT_VERSION = 'tv-season-holding-v1'
WARNING = (
    'Live scans may permanently delete one verified older season per scan after its Holding grace period. '
    'The show must still have the one-season tag. Favorites and keep tags protect the season. '
    'The latest season and Specials are preserved. Deleted files cannot be restored by the auditor.'
)


def validate_season_deletion(settings):
    from app.json_readonly_scan import _bool, _days

    enabled = _bool(settings, FLAG, 'false')
    if enabled and (settings.get(CONSENT_KEY) != CONSENT_VERSION
                    or not _bool(settings, 'ENABLE_TV_SEASON_RETENTION', 'false')
                    or _days(settings, 'HOLDING_DAYS', '7') < 1):
        raise ValueError('Season deletion requires season retention, at least one Holding day, and explicit acknowledgment.')
    return enabled
