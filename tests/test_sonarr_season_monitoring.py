from copy import deepcopy
from io import BytesIO
import json
from unittest.mock import patch

import pytest

from app.arr_title_transport import ArrTitleTransportError
from app.sonarr_season_monitoring import SonarrSeasonMonitoring


def client():
    return SonarrSeasonMonitoring(base_url='http://private-host', token='private-token',
                                  source_path='/media/TV/Example', title_folder='Example',
                                  series_id=17, season=1)


def record():
    return {'id': 17, 'path': '/media/TV/Example', 'monitored': True, 'qualityProfileId': 7,
            'seasons': [{'seasonNumber': 0, 'monitored': False},
                        {'seasonNumber': 1, 'monitored': True},
                        {'seasonNumber': 2, 'monitored': True}]}


def episodes(monitored):
    return [{'id': 31, 'seriesId': 17, 'seasonNumber': 1, 'monitored': monitored}]


def response(value, status):
    result = BytesIO(json.dumps(value).encode())
    result.status = status
    return result


def test_sonarr_updates_only_one_season_and_reads_back_twice():
    monitor = client()
    original = record()
    updated = deepcopy(original)
    updated['seasons'][1]['monitored'] = False
    replies = [response(original, 200), response(episodes(True), 200), response(updated, 202),
               response(updated, 200), response(episodes(False), 200),
               response(updated, 200), response(episodes(False), 200)]
    with patch.object(monitor._transport._opener, 'open', side_effect=replies) as opened:
        monitor.set(False, expected=True)
        requests = [call.args[0] for call in opened.call_args_list]
        assert [request.get_method() for request in requests] == ['GET', 'GET', 'PUT', 'GET', 'GET', 'GET', 'GET']
        assert requests[2].full_url.endswith('/api/v3/series/17?moveFiles=false')
        assert json.loads(requests[2].data) == updated
        with pytest.raises(ArrTitleTransportError, match='no retry'):
            monitor.set(False, expected=True)


@pytest.mark.parametrize('problem', ['path', 'duplicate', 'changed_flag'])
def test_identity_and_monitoring_conflicts_block_before_put(problem):
    monitor = client()
    row = record()
    if problem == 'path':
        row['path'] = '/other/Example'
    elif problem == 'duplicate':
        row['seasons'].append(row['seasons'][1])
    else:
        row['seasons'][1]['monitored'] = False
    with patch.object(monitor._transport._opener, 'open', return_value=response(row, 200)) as opened:
        with pytest.raises(ArrTitleTransportError):
            monitor.set(False, expected=True)
        assert opened.call_count == 1


def test_other_season_change_leaves_outcome_unresolved():
    monitor = client()
    original = record()
    changed = deepcopy(original)
    changed['seasons'][1]['monitored'] = False
    changed['seasons'][2]['monitored'] = False
    replies = [response(original, 200), response(episodes(True), 200),
               response({'id': 17}, 202), response(changed, 200)]
    with patch.object(monitor._transport._opener, 'open', side_effect=replies):
        with pytest.raises(ArrTitleTransportError, match='readback mismatch'):
            monitor.set(False, expected=True)



def test_individual_episode_override_blocks_before_put():
    monitor = client()
    replies = [response(record(), 200), response(episodes(False), 200)]
    with patch.object(monitor._transport._opener, 'open', side_effect=replies) as opened:
        with pytest.raises(ArrTitleTransportError, match='individual episode monitoring'):
            monitor.set(False, expected=True)
        assert [call.args[0].get_method() for call in opened.call_args_list] == ['GET', 'GET']
