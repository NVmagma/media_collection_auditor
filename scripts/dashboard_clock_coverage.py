"""Count missing tracking dates without printing titles, paths, or settings."""
from datetime import datetime
import json
import os
from pathlib import Path
import sys

STAGES={'Waiting':'first_seen','Holding':'queued','Removal':'in_removal','Keep':'keep_seen'}


def coverage(state,settings):
    result=[]
    media=settings.get('MEDIA_PATH','/media')
    for library,prefix,enabled,default in (('Movies','RADARR','ENABLE_MOVIES','true'),('TV','SONARR','ENABLE_TV','false')):
        if str(settings.get(enabled,default)).lower()!='true':continue
        key_prefix='TV/' if library=='TV' else ''
        for stage,section in STAGES.items():
            kind='TRANSIENT' if stage=='Waiting' else stage.upper()
            suffix={'Waiting':'','Holding':'_hold','Removal':'_removal','Keep':'_keep'}[stage]
            directory=settings.get(prefix+'_'+kind+'_PATH') or str(Path(media)/(library+suffix))
            row={'library':library,'stage':stage,'status':'observed','folders':0,
                'recorded_dates':0,'missing_dates':0,'invalid_dates':0,'case_only_candidates':0,
                'records_in_other_stages':0,'unmatched_tracking_records':0}
            try:
                with os.scandir(directory) as entries:
                    names=[]
                    for entry in entries:
                        if entry.is_dir(follow_symlinks=False):names.append(entry.name)
                        if len(names)>100000:raise OSError('Inventory bound exceeded')
            except OSError:
                row['status']='directory_unavailable';result.append(row);continue
            clocks={key:value for key,value in state.get(section,{}).items()
                if (key.startswith('TV/'))==(library=='TV')}
            folded={}
            for key in clocks:folded.setdefault(key.casefold(),[]).append(key)
            present={key_prefix+name for name in names}
            row['folders']=len(names)
            row['unmatched_tracking_records']=len(set(clocks)-present)
            for key in present:
                if key in clocks:
                    try:datetime.fromisoformat(clocks[key].replace('Z','+00:00'))
                    except (ValueError,TypeError,AttributeError,OverflowError):row['invalid_dates']+=1
                    else:row['recorded_dates']+=1
                else:
                    row['missing_dates']+=1
                    if len(folded.get(key.casefold(),[]))==1:row['case_only_candidates']+=1
                    if any(key in state.get(other,{}) for other in STAGES.values() if other!=section):
                        row['records_in_other_stages']+=1
            result.append(row)
    return {'status':'dashboard_clock_coverage_observed','read_only':True,'freshness_verified':False,
            'automatic_action':'none','media_actions_authorized':False,'libraries':result}


def main():
    try:
        from app.json_validation import parse_unique_json
        raw=sys.stdin.buffer.read(16*1024*1024+1)
        if len(raw)>16*1024*1024:raise ValueError('Bounded container observation required')
        items=parse_unique_json(raw)
        if not isinstance(items,list) or len(items)!=1:raise ValueError('One auditor required')
        env=dict(item.split('=',1) for item in items[0]['Config']['Env'])
        backend=env.get('AUDITOR_STATE_BACKEND','json')
        if backend=='json':
            from app.config_store import KEYS
            from app.dashboard_tracking_snapshot import read_json_dashboard_snapshot
            config=parse_unique_json(Path(env.get('WEB_CONFIG_FILE','/app/logs/auditor_config.json')).read_bytes())
            effective={**env,**{key:str(value) for key,value in config.items() if key in KEYS}}
            state=read_json_dashboard_snapshot(effective.get('STATE_FILE','/app/logs/auditor_state.json'),require_existing=True).state
            report=coverage(state,effective)
        else:raise ValueError('Unsupported backend')
        report['storage_authority']=backend
    except Exception:
        print(json.dumps({'status':'dashboard_clock_coverage_unavailable','read_only':True,'automatic_action':'none'}));return 2
    print(json.dumps(report,sort_keys=True));return 0

if __name__=='__main__':raise SystemExit(main())
