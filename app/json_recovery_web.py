"""Admin-only explicit JSON operation review. No automatic recovery or move replay."""
from copy import deepcopy
from time import monotonic
from urllib.parse import urlsplit
from flask import Blueprint,request,render_template

from app.json_operation_recovery import (review_pending_move,reconcile_pending_move,
    review_pending_sync,acknowledge_pending_sync,finish_pending_sync)
from app.json_scan_control import KEY
from app.json_tracking_store import JsonTrackingStore
from app.json_worker_service import enabled,settings_snapshot
from app.sqlite_arr_title_transport import ArrTitleUpdate


def create_blueprint(is_admin,load_settings=settings_snapshot):
    routes=Blueprint('json_recovery',__name__)
    def authorized():
        if not enabled(): return ('Not found',404)
        if not is_admin(): return ('Administrator sign-in required',401)
        if request.method=='POST':
            origin=request.headers.get('Origin') or request.headers.get('Referer')
            if not origin or urlsplit(origin).netloc != request.host: return ('Invalid origin',403)
        return None

    def adapters(values):
        def client(req):
            prefix='SONARR' if req.library=='TV' else 'RADARR'
            return ArrTitleUpdate(service=req.service,base_url=values.get(prefix+'_URL',''),
                token=values.get(prefix+'_API_KEY',''),source_path=req.arr_source_path,title_folder=req.title)
        def read(req):
            transport=client(req)
            return transport._request('GET',transport._url+'/'+str(req.title_id),monotonic()+30)
        def send(req):
            return client(req)(dict(service=req.service,title_id=req.title_id,
                root=req.arr_destination_root,monitored=req.monitored))
        return read,send

    @routes.route('/operation-recovery',methods=['GET','POST'])
    def recovery():
        refused=authorized()
        if refused: return refused
        review=None; result=None; error=None; pending=None
        try:
            values=deepcopy(load_settings())
            if values.get('AUDITOR_STATE_BACKEND','json') != 'json': raise RuntimeError('Storage mismatch')
            store=JsonTrackingStore(values.get('STATE_FILE','/app/logs/auditor_state.json'))
            with store.session() as session:
                journal=session.state.get(KEY,{}).get('journal')
                if journal:
                    pending={key:journal[key] for key in ('kind','library','title')}
            if request.method=='POST':
                if not pending: raise RuntimeError('No selected operation')
                read,send=adapters(values)
                action=request.form.get('action')
                if action=='review':
                    review=(review_pending_move if pending['kind']=='move' else review_pending_sync)(store,read_record=read)
                else:
                    actions={'record_move':reconcile_pending_move,'cancel_unperformed_move':reconcile_pending_move,
                             'acknowledge':acknowledge_pending_sync,'finish_arr_sync':finish_pending_sync}
                    if action not in actions: raise ValueError('Unknown action')
                    kwargs=dict(read_record=read,expected_fingerprint=request.form.get('fingerprint'))
                    if action=='finish_arr_sync': kwargs['send_update']=send
                    result=actions[action](store,**kwargs)
        except Exception:
            error='The operation could not be verified. The retained journal was not automatically cleared or replayed. Review again before another action.'
        return render_template('json_recovery.html',pending=pending,review=review,result=result,error=error), (409 if error else 200), {'Cache-Control':'no-store'}
    return routes
