"""Render synthetic backup metadata only; no private payloads or file operations."""
import os
from pathlib import Path
from unittest.mock import patch
os.environ.setdefault('WEB_SESSION_SECRET','synthetic-backup-browser-secret')
import web
from app import backup_workspace


def render():
    rows=[dict(id=str(n)*32,status='verified' if n!=4 else 'unavailable',
        captured='2026-11-04T12:00:00+00:00',counts={key:3 for key in ('first_seen','queued','in_removal','keep_seen','arr_sync_pending')},pending=n==3)
        for n in range(1,6)]
    listing=dict(items=rows,page=1,pages=2,total=6)
    with patch.object(web,'current_user',return_value={'name':'Synthetic admin','admin':True}), \
         patch.object(web,'load_config',return_value={'DAILY_RUN_TIMEZONE':'America/Los_Angeles'}), \
         patch.object(backup_workspace,'inventory',return_value=listing):
        response=web.app.test_client().get('/backups')
        assert response.status_code==200
        return response.data


if __name__=='__main__':
    import sys
    Path(sys.argv[1]).write_bytes(render())
