"""Initialize an empty appdata directory. Never reuse or replace existing files."""
from datetime import datetime,timedelta,timezone
import json,os
from pathlib import Path
from app.filesystem_paths import _open_directory
from app.json_backup import _write
from app.json_scan_control import initialize_control
from app.json_tracking_store import JsonTrackingStore
from app.tracking_schema import SECTIONS


def initialize(directory):
    root=Path(directory);fd=_open_directory(str(root))
    try:
        if os.listdir(fd):raise RuntimeError('Initialization requires an empty logs directory')
        _write(fd,'auditor_state.json',(json.dumps({name:{} for name in SECTIONS})+'\n').encode())
        _write(fd,'auditor_config.json',b'{}\n')
        with JsonTrackingStore(root/'auditor_state.json').session() as session:
            initialize_control(session,previous_started_at=datetime.now(timezone.utc)-timedelta(hours=1))
        return {'status':'json_tracking_initialized','media_actions_performed':False}
    finally:os.close(fd)


if __name__=='__main__':
    print(json.dumps(initialize('/app/logs')))
