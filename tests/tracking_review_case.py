"""Synthetic local-tracking comparison browser fixture; no production sources."""
import os
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('WEB_SESSION_SECRET','synthetic-tracking-browser-secret')
import web


def render():
    state={'first_seen':{f'Absent {n:03}':'2020-01-01' for n in range(60)}}
    inventory=dict(Waiting=[dict(library='Movies',title='New folder')],Holding=[],Keep=[],Removal=[])
    config={'ENABLE_MOVIES':'true','ENABLE_TV':'true','DAILY_RUN_TIMEZONE':'America/Los_Angeles'}
    with patch.object(web,'current_user',return_value={'name':'Synthetic admin','admin':True}), \
         patch.object(web,'load_state',return_value=state),patch.object(web,'load_config',return_value=config), \
         patch.object(web,'read_history',return_value=[]),patch.object(web,'filesystem_stages',return_value=(inventory,[])):
        response=web.app.test_client().get('/tracking-review')
        assert response.status_code==200
        return response.data


if __name__=='__main__':
    import sys
    Path(sys.argv[1]).write_bytes(render())
