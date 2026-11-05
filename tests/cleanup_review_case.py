"""Render recorded-only synthetic cleanup pages; no production inputs or requests."""
import os
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('WEB_SESSION_SECRET','synthetic-cleanup-browser-secret')
import web
from app.orphan_cleanup import STATE_KEY


def render(view='observing'):
    def folder(n):
        return dict(library='Movies',title=f'Leftover {n:03}',media_key=f'Leftover {n:03}',stage='Waiting',
                    source_root='/media/Movies',identity=[1,n+2],root_identity=[1,1],fingerprint='a'*64)
    saved={STATE_KEY:dict(schema_version=1,observations={f'Leftover {n:03}':dict(folder=folder(n),
        first_observed_at='2026-11-04T02:00:00+00:00',last_observed_at='2026-11-04T14:00:00+00:00')
        for n in range(27)},quarantined={'b'*32:dict(folder=folder(99),observed_at='2026-11-04T14:00:00+00:00',
        quarantine_path='/media/.auditor-orphans')})}
    with patch.object(web,'current_user',return_value={'name':'Synthetic admin','admin':True}), \
         patch.object(web,'load_state',return_value=saved),patch.object(web,'read_history',return_value=[]), \
         patch.object(web,'load_config',return_value={'ORPHAN_CLEANUP_ENABLED':'false','DAILY_RUN_TIMEZONE':'America/Los_Angeles'}):
        response=web.app.test_client().get('/cleanup-review?view='+view)
        assert response.status_code==200
        return response.data


if __name__=='__main__':
    import sys
    for view in ('observing','blocked','quarantined'):
        Path(sys.argv[1]+'.'+view+'.html').write_bytes(render(view))
