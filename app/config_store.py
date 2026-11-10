"""Save application settings. Old container variables still work while an existing install is being updated."""
import json
import os
from pathlib import Path

CONFIG_FILE = Path(os.environ.get("WEB_CONFIG_FILE", "/app/logs/auditor_config.json"))
FIELDS = {
    "Connections": ["JELLYFIN_HOST_URL", "JELLYFIN_API_TOKEN", "RADARR_URL", "RADARR_API_KEY", "SONARR_URL", "SONARR_API_KEY"],
    "Libraries": ["ENABLE_MOVIES", "ENABLE_TV", "MEDIA_PATH", "DISLIKE_TAG", "PROTECT_TAG", "KEEP_TAG", "FAVORITES_TRIGGER_KEEP", "JELLYFIN_REFRESH_AFTER_AUDIT", "TV_NEW_EPISODES_RESET_CLOCK", "ENABLE_TV_SEASON_RETENTION", "ENABLE_SEASON_PRUNING", "KEEP_ALL_SEASONS_TAG", "SEASON_PRUNE_GRACE_DAYS", "SEASON_PRUNE_AFTER_NEW_SEASON_DAYS"],
    "Lifecycle": ["MOVIE_WAIT_DAYS", "TV_WAIT_DAYS", "HOLDING_DAYS", "REMOVAL_DAYS", "RUN_INTERVAL_HOURS", "DAILY_RUN_TIME", "DAILY_RUN_TIMEZONE"],
    "Safety": ["ALLOW_TV_SEASON_DELETE", "ORPHAN_CLEANUP_ENABLED", "ALLOW_PERMANENT_DELETE", "DRY_RUN", "MAX_ACTIONS_PER_RUN", "ALLOW_FILESYSTEM_DELETE", "ALLOW_CROSS_FILESYSTEM_MOVES"],
    "Notifications": ["NOTIFY_DISCORD_WEBHOOK_URL", "NOTIFY_NTFY_URL", "NOTIFY_NTFY_TOKEN", "NOTIFY_WEBHOOK_URL", "NOTIFY_ON_DRY_RUN", "NOTIFY_OPERATIONAL_FAILURES", "NOTIFY_LEAVING_SOON_DIGEST"],
}
FIELDS['Paths'] = [prefix+'_'+stage+'_PATH' for prefix in ('RADARR','SONARR')
                   for stage in ('TRANSIENT','HOLDING','KEEP','REMOVAL')]
FIELDS['Paths'] += [prefix+'_APP_'+stage+'_PATH' for prefix in ('RADARR','SONARR')
                    for stage in ('HOLDING','KEEP','REMOVAL')]
FIELDS['Paths'] += ['TV_SEASON_HOLDING_PATH']
FIELDS['Integrations'] = ['INTEGRATION_API_TOKEN','INTEGRATION_API_TITLE_DETAILS',
    'INTEGRATION_API_MEDIA','INTEGRATION_API_COVERAGE','JELLYFIN_PUBLIC_URL',
    'INTEGRATION_API_BACKUP_DIRECTORY','INTEGRATION_API_BACKUP_IDENTITY',
    'INTEGRATION_API_BACKUP_FINGERPRINT']
FIELDS['Web'] = ['WEB_SECURE_COOKIE']
KEYS = set(sum(FIELDS.values(), []))
# Use the same canary settings list in the UI and the worker.
LIVE_CANARY_LOCKED_KEYS = frozenset(('DRY_RUN','MAX_ACTIONS_PER_RUN','MEDIA_PATH','DAILY_RUN_TIMEZONE',
    'ALLOW_PERMANENT_DELETE','ALLOW_FILESYSTEM_DELETE','ALLOW_CROSS_FILESYSTEM_MOVES','ENABLE_SEASON_PRUNING'))
SECRETS = {"JELLYFIN_API_TOKEN", "RADARR_API_KEY", "SONARR_API_KEY", "NOTIFY_DISCORD_WEBHOOK_URL", "NOTIFY_NTFY_TOKEN", "NOTIFY_WEBHOOK_URL"}
BOOLS = {"ALLOW_TV_SEASON_DELETE", "ORPHAN_CLEANUP_ENABLED", "ALLOW_PERMANENT_DELETE", "ENABLE_MOVIES", "ENABLE_TV", "FAVORITES_TRIGGER_KEEP", "JELLYFIN_REFRESH_AFTER_AUDIT", "TV_NEW_EPISODES_RESET_CLOCK", "ENABLE_TV_SEASON_RETENTION", "ENABLE_SEASON_PRUNING", "DRY_RUN", "ALLOW_FILESYSTEM_DELETE", "ALLOW_CROSS_FILESYSTEM_MOVES", "NOTIFY_ON_DRY_RUN", "NOTIFY_OPERATIONAL_FAILURES", "NOTIFY_LEAVING_SOON_DIGEST"}
INTS = {"MOVIE_WAIT_DAYS", "TV_WAIT_DAYS", "HOLDING_DAYS", "REMOVAL_DAYS", "MAX_ACTIONS_PER_RUN", "SEASON_PRUNE_GRACE_DAYS", "SEASON_PRUNE_AFTER_NEW_SEASON_DAYS"}
FLOATS = {"RUN_INTERVAL_HOURS"}
MINIMUM_ONE = {"HOLDING_DAYS", "REMOVAL_DAYS"}
DEFAULTS = {"ALLOW_TV_SEASON_DELETE":"false", "ENABLE_TV_SEASON_RETENTION":"false", "ORPHAN_CLEANUP_ENABLED":"false", "ALLOW_PERMANENT_DELETE":"false","DRY_RUN":"true","ENABLE_MOVIES":"true","ENABLE_TV":"false","MOVIE_WAIT_DAYS":"30","TV_WAIT_DAYS":"60","HOLDING_DAYS":"7","REMOVAL_DAYS":"7","RUN_INTERVAL_HOURS":"0","MAX_ACTIONS_PER_RUN":"10","DISLIKE_TAG":"not-at-all","PROTECT_TAG":"keep-forever","KEEP_TAG":"keep","FAVORITES_TRIGGER_KEEP":"true","JELLYFIN_REFRESH_AFTER_AUDIT":"false","TV_NEW_EPISODES_RESET_CLOCK":"true","ENABLE_SEASON_PRUNING":"false","KEEP_ALL_SEASONS_TAG":"keep-all-seasons","SEASON_PRUNE_GRACE_DAYS":"30","SEASON_PRUNE_AFTER_NEW_SEASON_DAYS":"7","NOTIFY_ON_DRY_RUN":"false","NOTIFY_OPERATIONAL_FAILURES":"false","NOTIFY_LEAVING_SOON_DIGEST":"true","ALLOW_FILESYSTEM_DELETE":"false","ALLOW_CROSS_FILESYSTEM_MOVES":"false","MEDIA_PATH":"/media"}

SECRETS.add('INTEGRATION_API_TOKEN')
BOOLS.update(('INTEGRATION_API_TITLE_DETAILS','INTEGRATION_API_MEDIA','INTEGRATION_API_COVERAGE','WEB_SECURE_COOKIE'))
DEFAULTS.update({key:'false' for key in ('INTEGRATION_API_TITLE_DETAILS','INTEGRATION_API_MEDIA','INTEGRATION_API_COVERAGE','WEB_SECURE_COOKIE')})

# Save Docker's original values before the worker applies saved settings. If an
# override is removed, fall back to these original values.
_INITIAL_ENVIRONMENT = dict(os.environ)


def initial_environment():
    return dict(_INITIAL_ENVIRONMENT)


def load_config():
    try:
        data = json.loads(CONFIG_FILE.read_text())
        return {k: str(v) for k, v in data.items() if k in KEYS} if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}

def validate(key, value):
    value = value.strip()
    if key == "DAILY_RUN_TIME" and value:
        import re
        if not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", value):
            raise ValueError("DAILY_RUN_TIME: enter HH:MM in 24-hour format")
    if key == "DAILY_RUN_TIMEZONE" and value:
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("DAILY_RUN_TIMEZONE: enter an available IANA time zone") from None
    if key in BOOLS and value.lower() not in ("true", "false"):
        raise ValueError(f"{key}: select true or false")
    if key in INTS or key in FLOATS:
        try:
            n = int(value) if key in INTS else float(value)
        except ValueError:
            raise ValueError(f"{key}: enter a valid number")
        if not 0 <= n <= 100000 or (key in MINIMUM_ONE and n < 1):
            raise ValueError(f"{key}: number is outside the allowed range")
    if key.endswith("_URL") or key == "JELLYFIN_HOST_URL":
        if value and not value.startswith(("http://", "https://")):
            raise ValueError(f"{key}: URL must start with http:// or https://")
    if key == "MEDIA_PATH" and not value.startswith("/"):
        raise ValueError("MEDIA_PATH must be an absolute container path")
    if key == 'INTEGRATION_API_TOKEN' and value:
        import re
        if not re.fullmatch(r'[A-Za-z0-9_-]{32,256}', value):
            raise ValueError('Integration token must contain 32–256 URL-safe characters')
    if key.endswith('_PATH') and value:
        from app.filesystem_paths import _canonical
        try: _canonical(value)
        except ValueError: raise ValueError(f'{key}: enter an absolute canonical container path') from None
    if len(value) > 2048:
        raise ValueError(f"{key}: value is too long")
    return value.lower() if key in BOOLS else value

def save_config(values):
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = CONFIG_FILE.with_suffix(".tmp")
    with temp.open("w") as handle:
        json.dump(values, handle, indent=2)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temp, 0o600)
    os.replace(temp, CONFIG_FILE)

FIELD_HELP = {
  "ALLOW_TV_SEASON_DELETE": ["Permanently Delete Expired TV Seasons", "Default off. Delete eligible older seasons only after their Leaving Soon grace period and fresh protection checks."],
  "ENABLE_TV_SEASON_RETENTION": ["Stage Older TV Seasons", "Opt in to one-season staging and keep-all restoration. Requires a separate writable season Holding directory on the same media filesystem."],
  "ORPHAN_CLEANUP_ENABLED": ["Quarantine Orphan Metadata Folders", "Default off. After 24 hours of unchanged observations, quarantine known sidecars only when no video exists and fresh Arr/Jellyfin checks confirm absence. Keep and unknown files are preserved; nothing is permanently deleted."],
  "DAILY_RUN_TIME": ["Daily Scan Time", "Daily start in HH:MM. Manual scans share the one-hour cooldown; overlapping scans are blocked."],
  "DAILY_RUN_TIMEZONE": ["Scan Time Zone", "IANA time zone for daily scans and lifecycle dates, such as America/Los_Angeles."],
  "JELLYFIN_REFRESH_AFTER_AUDIT": ["Refresh Jellyfin After Audit", "Request a Jellyfin library scan once after an audit that successfully moved media. Disabled for dry runs and audits with no moves."],
  "JELLYFIN_HOST_URL": [
    "Jellyfin Server URL",
    "Address of your Jellyfin server, including its port."
  ],
  "JELLYFIN_API_TOKEN": [
    "Jellyfin API Key",
    "API key used to read favorites, tags and viewing activity."
  ],
  "RADARR_URL": [
    "Radarr Server URL",
    "Address of Radarr for managing movie entries."
  ],
  "RADARR_API_KEY": [
    "Radarr API Key",
    "API key from Radarr Settings → General."
  ],
  "SONARR_URL": [
    "Sonarr Server URL",
    "Address of Sonarr for managing TV series."
  ],
  "SONARR_API_KEY": [
    "Sonarr API Key",
    "API key from Sonarr Settings → General."
  ],
  "ENABLE_MOVIES": [
    "Manage Movies",
    "Include movies in audit runs."
  ],
  "ENABLE_TV": [
    "Manage TV Shows",
    "Include television series in audit runs."
  ],
  "MEDIA_PATH": [
    "Media Root Path",
    "Path inside the container, not the Unraid host path."
  ],
  "DISLIKE_TAG": [
    "Disliked Title Tag",
    "Jellyfin tag that makes a title eligible for holding."
  ],
  "PROTECT_TAG": [
    "Protected Title Tag",
    "Jellyfin tag that prevents removal of a title."
  ],
  "KEEP_TAG": ["Keep Title Tag", "Jellyfin tag that moves a title to Keep without using Jellyfin favorites."],
  "FAVORITES_TRIGGER_KEEP": ["Legacy Favorite Support", "Keep enabled during migration so existing Jellyfin favorites remain protected. Disable only after tagging and dry-run verification."],
  "TV_NEW_EPISODES_RESET_CLOCK": [
    "Reset Timer for New Episodes",
    "Restart a show's waiting period when new episodes appear."
  ],
  "ENABLE_SEASON_PRUNING": [
    "Prune Older TV Seasons",
    "Unavailable in this release. Whole-title Removal deletion is a separate opt-in."
  ],
  "KEEP_ALL_SEASONS_TAG": [
    "Keep All Seasons Tag",
    "Jellyfin tag that protects every season of a show."
  ],
  "SEASON_PRUNE_GRACE_DAYS": [
    "Season Pruning Grace Period",
    "Days a show must be in Keep before pruning is considered."
  ],
  "SEASON_PRUNE_AFTER_NEW_SEASON_DAYS": [
    "New Season Delay",
    "Wait this many days after a new season arrives before pruning."
  ],
  "MOVIE_WAIT_DAYS": [
    "Movie Waiting Period",
    "Days a new movie remains in the transient folder."
  ],
  "TV_WAIT_DAYS": [
    "TV Waiting Period",
    "Days a show remains in the transient folder."
  ],
  "HOLDING_DAYS": [
    "Holding Period",
    "Days in Holding before moving to Removal."
  ],
  "REMOVAL_DAYS": [
    "Removal Grace Period",
    "Days in Removal before permanent deletion is eligible."
  ],
  "RUN_INTERVAL_HOURS": [
    "Audit Interval (Hours)",
    "Hours between automatic audits. Set 0 for manual runs only after the initial startup audit."
  ],
  "DRY_RUN": [
    "Dry Run (Safe Mode)",
    "Preview planned changes without moving or deleting media."
  ],
  "MAX_ACTIONS_PER_RUN": [
    "Maximum Destructive Actions",
    "Limit hold, delete and season-prune operations per audit."
  ],
  "ALLOW_PERMANENT_DELETE": ["Allow Permanent Deletion (Master Switch)", "Default off. Allows Arr-managed deletion of whole titles after the Removal waiting period, with an explicit warning acknowledgement. At most one deletion per library per scan; dry run remains a preview. Season pruning is unavailable."],
  "ALLOW_FILESYSTEM_DELETE": [
    "Allow Direct File Deletion",
    "Permit deletion without Radarr or Sonarr; use with extreme care."
  ],
  "ALLOW_CROSS_FILESYSTEM_MOVES": [
    "Allow Cross-Filesystem Moves",
    "Permit slower copy-and-delete moves between mounts."
  ],
  "NOTIFY_DISCORD_WEBHOOK_URL": [
    "Discord Webhook",
    "Discord channel webhook for audit notifications."
  ],
  "NOTIFY_NTFY_URL": [
    "ntfy Topic URL",
    "Full URL of the ntfy topic that receives notifications."
  ],
  "NOTIFY_NTFY_TOKEN": [
    "ntfy Access Token",
    "Optional authentication token for a protected ntfy topic."
  ],
  "NOTIFY_WEBHOOK_URL": [
    "Custom Webhook URL",
    "Optional endpoint receiving audit event notifications."
  ],
  "NOTIFY_OPERATIONAL_FAILURES": [
    "Notify on Operational Failures",
    "Opt in to redacted scan/settings alerts using the destinations above. Preview alerts also require Notify During Dry Runs. One delivery attempt per incident and destination in this process; no automatic retry."
  ],
  "NOTIFY_ON_DRY_RUN": [
    "Notify During Dry Runs",
    "Send notifications for previews as well as real audits."
  ],
  "NOTIFY_LEAVING_SOON_DIGEST": [
    "Include Leaving Soon Titles",
    "Include the list of titles currently in Holding in notifications."
  ]
}


for _key in FIELDS['Paths']:
    FIELD_HELP[_key] = (_key.replace('_',' ').title(),
        'Optional absolute container path. Leave blank for the standard /media layout. Arr aliases must match the path used by that service.')
FIELD_HELP.update({
    'INTEGRATION_API_TOKEN': ('Read-only API Token','Enter a private random URL-safe token, 32–256 characters. Blank keeps the current token; use Disable API below to revoke it.'),
    'INTEGRATION_API_TITLE_DETAILS': ('API Title Lists','Allow read-only widgets to list tracked titles.'),
    'INTEGRATION_API_MEDIA': ('API Artwork Links','Allow widgets to include Jellyfin artwork and title links.'),
    'INTEGRATION_API_COVERAGE': ('API Coverage','Allow aggregate local folder and clock coverage reads.'),
    'JELLYFIN_PUBLIC_URL': ('Browser Jellyfin URL','Optional Jellyfin URL reachable by family browsers; falls back to the server URL.'),
    'INTEGRATION_API_BACKUP_DIRECTORY': ('Backup API Packet Path','Optional container path of the explicitly selected private backup packet.'),
    'INTEGRATION_API_BACKUP_IDENTITY': ('Backup API Packet Identity','Reviewed device:inode identity of the selected packet.'),
    'INTEGRATION_API_BACKUP_FINGERPRINT': ('Backup API Receipt Fingerprint','Reviewed SHA-256 of the selected completion receipt.'),
    'WEB_SECURE_COOKIE': ('HTTPS-only Login Cookie','Enable when accessing this app through HTTPS. HTTP login will no longer work until disabled.')
})


def setting(key, default=''):
    """Read web changes immediately; legacy variables support existing installs."""
    return load_config().get(key, os.environ.get(key, DEFAULTS.get(key, default)))


def redacted_config(config):
    """Export only the settings we allow sharing. Leave out credentials and URLs."""
    safe = ("ORPHAN_CLEANUP_ENABLED", "DRY_RUN", "ALLOW_PERMANENT_DELETE", "ALLOW_FILESYSTEM_DELETE",
            "ALLOW_CROSS_FILESYSTEM_MOVES", "ENABLE_MOVIES", "ENABLE_TV",
            "ENABLE_SEASON_PRUNING", "FAVORITES_TRIGGER_KEEP",
            "JELLYFIN_REFRESH_AFTER_AUDIT", "TV_NEW_EPISODES_RESET_CLOCK",
            "MOVIE_WAIT_DAYS", "TV_WAIT_DAYS", "HOLDING_DAYS",
            "REMOVAL_DAYS", "RUN_INTERVAL_HOURS", "MAX_ACTIONS_PER_RUN",
            "SEASON_PRUNE_GRACE_DAYS", "SEASON_PRUNE_AFTER_NEW_SEASON_DAYS")
    return {key: str(config[key]) for key in safe if key in config}
