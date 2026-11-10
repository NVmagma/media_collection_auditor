"""Update monitoring for one Sonarr season with one checked write."""
from hashlib import sha256
import json
from time import monotonic

from app.arr_catalog import canonical_arr_record_path
from app.arr_title_transport import ArrTitleTransportError, ArrTitleUpdate


class SonarrSeasonMonitoring:
    def __init__(self, *, base_url, token, source_path, title_folder, series_id, season,
                 verify_binding=None, deadline_tick=None):
        if type(series_id) is not int or series_id < 1 or type(season) is not int or season < 1:
            raise ValueError('Positive Sonarr series ID and regular season required')
        self.series_id, self.season = series_id, season
        self._transport = ArrTitleUpdate(service='sonarr', base_url=base_url, token=token,
                                         source_path=source_path, title_folder=title_folder,
                                         verify_binding=verify_binding, deadline_tick=deadline_tick)
        self.source_path = self._transport._source
        self._episode_url = self._transport._url.rsplit('/', 1)[0] + '/episode?seriesId=' + str(series_id)
        self._url = self._transport._url + '/' + str(series_id)
        self.endpoint_identity = sha256(self._url.encode()).hexdigest()
        self._used = False

    def _deadline(self):
        deadline = monotonic() + 10
        outer = self._transport._deadline
        return min(deadline, outer) if outer is not None else deadline

    def _read(self, deadline):
        row = self._transport._request('GET', self._url, deadline)
        try:
            if (type(row.get('id')) is not int or row['id'] != self.series_id
                    or canonical_arr_record_path(row.get('path')) != self.source_path
                    or type(row.get('monitored')) is not bool or not isinstance(row.get('seasons'), list)):
                raise ValueError()
            seasons = {}
            for item in row['seasons']:
                number, monitored = item['seasonNumber'], item['monitored']
                if type(number) is not int or number < 0 or number in seasons or type(monitored) is not bool:
                    raise ValueError()
                seasons[number] = monitored
            if self.season not in seasons:
                raise ValueError()
        except (ValueError, TypeError, KeyError):
            raise ArrTitleTransportError('Sonarr series or season identity changed') from None
        return row, seasons

    def _episode_ids(self, deadline, wanted):
        episodes = self._transport._request('GET', self._episode_url, deadline, response_type=list)
        seen, selected = set(), set()
        for row in episodes:
            if not isinstance(row, dict):
                raise ArrTitleTransportError('Sonarr episode inventory invalid')
            episode_id, season = row.get('id'), row.get('seasonNumber')
            if (type(episode_id) is not int or episode_id <= 0 or episode_id in seen
                    or type(row.get('seriesId')) is not int or row['seriesId'] != self.series_id
                    or type(season) is not int or season < 0 or type(row.get('monitored')) is not bool):
                raise ArrTitleTransportError('Sonarr episode inventory invalid')
            seen.add(episode_id)
            if season == self.season:
                if row['monitored'] is not wanted:
                    raise ArrTitleTransportError('Sonarr individual episode monitoring differs from its season')
                selected.add(episode_id)
        if not selected:
            raise ArrTitleTransportError('Sonarr season episodes unavailable')
        return selected

    def read(self):
        deadline = self._deadline()
        _, seasons = self._read(deadline)
        wanted = seasons[self.season]
        self._episode_ids(deadline, wanted)
        return wanted

    def set(self, wanted, *, expected):
        if type(wanted) is not bool or type(expected) is not bool or wanted is expected:
            raise ValueError('An explicit monitoring change is required')
        if self._used:
            raise ArrTitleTransportError('Season monitoring attempt already used; no retry')
        self._used = True
        deadline = self._deadline()
        row, seasons = self._read(deadline)
        if seasons[self.season] is not expected:
            raise ArrTitleTransportError('Sonarr monitoring changed before update')
        episode_ids = self._episode_ids(deadline, expected)
        series_monitored = row['monitored']
        for item in row['seasons']:
            if item['seasonNumber'] == self.season:
                item['monitored'] = wanted
        raw = json.dumps(row, allow_nan=False, separators=(',', ':')).encode()
        if len(raw) > 8 * 1024 * 1024:
            raise ArrTitleTransportError('Sonarr update resource too large')
        self._transport._request('PUT', self._url + '?moveFiles=false', deadline, raw)
        seasons[self.season] = wanted
        for _ in range(2):
            observed, observed_seasons = self._read(deadline)
            if observed_seasons != seasons or observed['monitored'] is not series_monitored:
                raise ArrTitleTransportError('Sonarr season readback mismatch; outcome unresolved')
            if self._episode_ids(deadline, wanted) != episode_ids:
                raise ArrTitleTransportError('Sonarr episode identities changed; outcome unresolved')
