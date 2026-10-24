"""Daily schedule calculation for the scheduled SQLite runner.

No worker, media operation or activation is performed here. Callers must persist
run ownership separately and never infer a move permit from a scheduled time.
"""
from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
import re
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


@dataclass(frozen=True)
class DailyRunSchedule:
    local_time: str
    timezone_name: str

    def __post_init__(self):
        if not isinstance(self.local_time, str) or not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', self.local_time):
            raise ValueError('Daily scan time must be HH:MM in 24-hour format')
        if not isinstance(self.timezone_name, str) or not self.timezone_name:
            raise ValueError('An explicit IANA time zone is required')
        try:
            ZoneInfo(self.timezone_name)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError('Daily scan time zone is unavailable') from exc

    def next_start(self, after):
        """Return the next strictly future UTC start; never catch up a missed slot.

        Spring-forward nonexistent times are skipped. Fall-back ambiguous times
        use the first occurrence only. This avoids two scheduled runs on one
        local date; durable run claiming must still prevent competing workers.
        """
        if not isinstance(after, datetime) or after.tzinfo is None or after.utcoffset() is None:
            raise ValueError('An aware current timestamp is required')
        current = after.astimezone(timezone.utc)
        zone = ZoneInfo(self.timezone_name)
        hour, minute = map(int, self.local_time.split(':'))
        date = current.astimezone(zone).date()
        # Covers skipped civil dates as well as ordinary DST gaps.
        for days in range(370):
            wall = datetime.combine(date + timedelta(days=days), time(hour, minute))
            candidate = wall.replace(tzinfo=zone, fold=0).astimezone(timezone.utc)
            if candidate.astimezone(zone).replace(tzinfo=None) != wall:
                continue
            if candidate > current:
                return candidate
        raise ValueError('No valid daily run time found in the scheduling horizon')
