"""Single-attempt preview update. Durable intent precedes each service action."""
from scripts.sqlite_preview_service import NAME, LABEL, container_id, validate_original, validate_preview


def handoff(*,engine,journal,captured,payload,image_id,precheck,health,install,validator=validate_preview,live_canary=False):
    old=container_id(captured['Id']);attempt=container_id(payload['Labels'][LABEL])
    archive=NAME+'_before_update_'+old[:12]
    if captured['State']['Running'] is not True:
        raise RuntimeError('Running reviewed original required')
    validate_original(engine.inspect(NAME),captured,name=NAME,running=True)
    if engine.inspect(archive,optional=True) is not None:raise RuntimeError('Retained name occupied')
    precheck()
    journal.begin({'schema_version':1,'original_container_id':old,'candidate_image_id':image_id,
        'attempt':attempt,'automatic_restoration':False,'media_actions_authorized':live_canary})
    journal.event('original_stop_requested');engine.stop(old)
    validate_original(engine.inspect(old),captured,name=NAME,running=False)
    journal.event('original_stopped')
    # A running preview may have changed since backup; prove it again offline.
    precheck()
    journal.event('original_archive_requested');engine.rename(old,archive)
    validate_original(engine.inspect(old),captured,name=archive,running=False)
    journal.event('original_archived')
    if engine.inspect(NAME,optional=True) is not None:raise RuntimeError('Replacement name occupied')
    journal.event('replacement_create_requested');new=engine.create(NAME,payload)
    journal.event('replacement_created',container_id=new)
    def check(running):
        validator(engine.inspect(new),identity=new,image_id=image_id,request_id=attempt,payload=payload,running=running)
    check(False)
    journal.event('replacement_start_requested',container_id=new);engine.start(new);check(True)
    journal.event('replacement_started',container_id=new)
    health(new);check(True)
    journal.event('replacement_health_verified',container_id=new)
    validate_original(engine.inspect(old),captured,name=archive,running=False)
    journal.event('template_install_requested');install();check(True)
    journal.event('update_complete',container_id=new)
    return {'status':'candidate_preview_update_complete','container_id':new,'original_container_retained':True,
        'automatic_restoration':False,'media_actions_authorized':False}


def recover(*,engine,journal,captured,payload,image_id,new_id,precheck,restore_template,health,validator=validate_preview):
    """Explicit recovery with an exact reviewed replacement ID, never discovery."""
    old=container_id(captured['Id']);attempt=container_id(payload['Labels'][LABEL])
    current=engine.inspect(old);archive=NAME+'_before_update_'+old[:12]
    if current['Name'] not in ('/'+NAME,'/'+archive):raise RuntimeError('Original role changed')
    validate_original(current,captured,name=current['Name'][1:],running=False)
    if new_id is not None:
        new_id=container_id(new_id);live=engine.inspect(new_id)
        validator(live,identity=new_id,image_id=image_id,request_id=attempt,payload=payload,running=live['State']['Running'])
        if engine.inspect(NAME+'_update_retained_'+new_id[:12],optional=True) is not None:
            raise RuntimeError('Retained replacement name occupied')
    occupant=engine.inspect(NAME,optional=True)
    if occupant is not None and occupant['Id'] not in (old,new_id):
        raise RuntimeError('Unknown service occupant requires review')
    if new_id is None and current['Name']=='/'+archive and occupant is not None:
        raise RuntimeError('Replacement identity must be supplied explicitly')
    precheck()
    journal.begin({'schema_version':1,'original_container_id':old,'replacement_id':new_id,
        'automatic_restoration':False,'media_actions_authorized':False})
    if new_id is not None and live['State']['Running']:
        journal.event('replacement_stop_requested',container_id=new_id);engine.stop(new_id)
        validator(engine.inspect(new_id),identity=new_id,image_id=image_id,request_id=attempt,payload=payload,running=False)
        journal.event('replacement_stopped',container_id=new_id)
    precheck()
    journal.event('template_restore_requested');restore_template();journal.event('template_restored')
    if new_id is not None:
        journal.event('replacement_archive_requested',container_id=new_id)
        engine.rename(new_id,NAME+'_update_retained_'+new_id[:12]);journal.event('replacement_archived',container_id=new_id)
    if current['Name']!='/'+NAME:
        journal.event('original_name_restore_requested');engine.rename(old,NAME);journal.event('original_name_restored')
    validate_original(engine.inspect(old),captured,name=NAME,running=False)
    journal.event('original_start_requested');engine.start(old)
    validate_original(engine.inspect(old),captured,name=NAME,running=True);health(old)
    journal.event('recovery_complete')
    return {'status':'candidate_update_original_recovered','original_container_retained':True,
        'replacement_container_retained':new_id is not None,'automatic_restoration':False,'media_actions_authorized':False}
