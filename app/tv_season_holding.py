"""Read-only dashboard projection of recorded TV season staging."""
from datetime import datetime, timedelta, timezone

from app.dashboard_tracking_snapshot import observation_datetime
from app.title_identity import validate_title_folder
from app.tv_season_move import ARCHIVE, SEASON_FOLDER


def holding_seasons(state, *, holding_days, display_zone=None, now=None):
    now = datetime.now(timezone.utc) if now is None else now
    archive = state.get(ARCHIVE, {})
    if not isinstance(archive, dict):
        return {'rows': [], 'incomplete': True}
    rows = []
    incomplete = False
    for key, record in archive.items():
        try:
            prefix, title, season_text = key.split('/')
            validate_title_folder(title)
            folder = SEASON_FOLDER.fullmatch(record['name'])
            if prefix != 'TV' or not folder or int(folder[1]) < 1 or str(int(folder[1])) != season_text:
                raise ValueError('Invalid staged season identity')
            stamp = datetime.fromisoformat(record['staged_at'])
            if stamp.tzinfo is None or stamp > now:
                raise ValueError('Invalid staging time')
            ends = stamp + timedelta(days=holding_days) if holding_days is not None else None
        except (AttributeError, ValueError, TypeError, KeyError, OverflowError):
            incomplete = True
            continue
        rows.append({'title': title, 'season': int(season_text), 'staged_at': stamp, 'ends_at': ends})
    rows.sort(key=lambda row: (row['staged_at'], row['title'].casefold(), row['title'], row['season']))
    for row in rows:
        ends = row.pop('ends_at')
        row['grace_ended'] = ends is not None and ends <= now
        row['grace_ends_display'] = observation_datetime(ends.isoformat(), display_zone) if ends else None
        row['staged_display'] = observation_datetime(row.pop('staged_at').isoformat(), display_zone)
    return {'rows': rows, 'incomplete': incomplete}
