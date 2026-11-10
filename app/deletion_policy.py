"""Require saved consent before Arr can delete a title from Removal. No filesystem fallback."""

CONSENT_KEY = 'REMOVAL_DELETION_CONSENT'
CONSENT_VERSION = 'arr-removal-v1'
WARNING = ('Enabling Removal deletion allows scheduled and manual live scans to ask Radarr/Sonarr '
    'to delete an entire movie or TV series, including all episodes and files in its Removal folder, '
    'after the Removal waiting period. The Arr record is removed and excluded from import lists. '
    'This may be irreversible; the auditor cannot restore deleted files. Arr recycling-bin settings '
    'may retain files, so immediate space recovery is not guaranteed. Keep, keep-forever, '
    'keep-all-seasons and favorites block deletion. Missing protection information blocks deletion. '
    'Initially at most one title per library per scan can be deleted, within the existing action limits. '
    'Dry run only previews. Season deletion has separate consent. Direct filesystem deletion of whole titles remains unavailable.')


def enabled(settings):
    from app.json_readonly_scan import _bool
    return _bool(settings, 'ALLOW_PERMANENT_DELETE', 'false')


def validate_consent(settings):
    from app.json_readonly_scan import _days
    if enabled(settings):
        if settings.get(CONSENT_KEY) != CONSENT_VERSION:
            raise ValueError('Read and acknowledge the Removal deletion warning before enabling deletion.')
        if _days(settings, 'REMOVAL_DAYS', '7') < 1:
            raise ValueError('Removal deletion requires a waiting period of at least one day.')
    return enabled(settings)


def protected(signals):
    names = {'played', 'favorite', 'disliked', 'keep', 'keep_all', 'protected'}
    if not isinstance(signals, dict) or not names <= signals.keys() or any(type(signals[k]) is not bool for k in names):
        raise RuntimeError('Complete fresh Jellyfin protection required for deletion')
    return any(signals[k] for k in ('favorite', 'keep', 'keep_all', 'protected'))
