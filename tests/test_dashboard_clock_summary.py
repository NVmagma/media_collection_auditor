"""Keep missing dates visible without creating new lifecycle clocks."""
from copy import deepcopy
from app.dashboard_tracking_snapshot import summarize_dashboard_clocks


def test_tower_shaped_counts_are_preserved_without_resetting_missing_dates():
    state={'first_seen':{},'queued':{},'keep_seen':{}}
    stages={'Waiting':[],'Holding':[],'Removal':[],'Keep':[]}
    for library,total,tracked in (('Movies',513,454),('TV',69,66)):
        for index in range(total):
            title='Fixture '+str(index);key=('TV/' if library=='TV' else '')+title
            since='2026-01-01T11:30:00' if index<tracked else None
            stages['Waiting'].append({'title':title,'library':library,'since':since})
            if since:state['first_seen'][key]=since
    for index in range(2):state['first_seen']['TV/Unmatched '+str(index)]='2026-01-01T11:30:00'
    for stage,section,total in (('Holding','queued',4),('Keep','keep_seen',13)):
        for index in range(total):
            title=stage+str(index);state[section][title]='2026-01-01T11:30:00'
            stages[stage].append({'title':title,'library':'Movies','since':state[section][title]})
    before=deepcopy((state,stages))
    result=summarize_dashboard_clocks(state,stages,[],libraries=['Movies','TV'])
    waiting={row['library']:row for row in result['rows'] if row['stage']=='Waiting'}
    assert waiting['Movies']['missing_dates']==59 and waiting['TV']['missing_dates']==3
    assert result['missing_dates']==62 and result['records_without_stage_folder']==2
    assert result['complete'] and not result['freshness_verified']
    assert (state,stages)==before


def test_missing_mount_and_unavailable_tracking_do_not_claim_zero_gaps():
    stages={'Waiting':[{'library':'Movies','title':'Fixture','since':None}]}
    result=summarize_dashboard_clocks({},stages,['Movies Holding: directory unavailable'],libraries=['Movies'])
    assert not result['complete']
    holding=next(row for row in result['rows'] if row['stage']=='Holding')
    assert holding['folders'] is None and holding['missing_dates'] is None
    result=summarize_dashboard_clocks({},stages,[],libraries=['Movies'],tracking_available=False)
    assert not result['complete'] and all(row['missing_dates'] is None for row in result['rows'])


def test_other_stage_clock_never_fills_a_waiting_date():
    state={'queued':{'Same':'2026-01-01T11:30:00'}}
    stages={'Waiting':[{'library':'Movies','title':'Same','since':None}]}
    result=summarize_dashboard_clocks(state,stages,[],libraries=['Movies'])
    assert result['rows'][0]['missing_dates']==1
    assert result['records_without_stage_folder']==1
