"""Administrator backup controls. These routes never restore over active files."""
import hmac,re,secrets,os
from urllib.parse import urlsplit
from flask import Blueprint,request,session,render_template,redirect,url_for
from app import backup_workspace as workspace
from app.state_lock import StateLockBusy

MESSAGES={'backup_created':'Private tracking/settings backup created and verified.',
          'backup_verified':'The selected backup receipt and payload hashes verified.',
          'restore_copy_verified':'Disposable restore copy verified byte-for-byte. No worker was started and active files were not restored.'}


def create_blueprint(*,is_admin,paths,display_time):
    bp=Blueprint('backups',__name__)

    @bp.before_request
    def authorize():
        if not is_admin():return 'Administrator access required.',403
        if os.environ.get('AUDITOR_STATE_BACKEND','json')!='json':return 'JSON backups unavailable.',404
        if request.method=='POST':
            origin=request.headers.get('Origin')
            csrf=request.form.get('csrf');stored=session.get('backup_csrf')
            try:same_origin=bool(origin) and urlsplit(origin).netloc==request.host
            except ValueError:same_origin=False
            if (not same_origin or not isinstance(csrf,str) or not isinstance(stored,str)
                    or not hmac.compare_digest(csrf.encode(),stored.encode())):
                return 'Invalid request. Reload Backups before trying again.',403

    @bp.after_request
    def no_cache(response):
        response.headers['Cache-Control']='no-store'
        return response

    @bp.route('/backups',methods=['GET','POST'])
    def page():
        session.setdefault('backup_csrf',secrets.token_urlsafe(32))
        state_file,config_file=paths()
        message=None;error=None;status=200
        if request.method=='POST':
            if (set(request.form)-{'csrf','action','identifier'} or
                    any(len(request.form.getlist(key))!=1 for key in request.form)):
                return 'Invalid backup action.',400
            action=request.form.get('action');identifier=request.form.get('identifier')
            try:
                if action=='create':result=workspace.create(state_file=state_file,config_file=config_file)
                elif action=='verify':result=workspace.verify_backup(config_file=config_file,identifier=identifier)
                elif action=='test_restore':result=workspace.test_restore(config_file=config_file,identifier=identifier)
                else:return 'Unknown backup action.',400
                session['backup_notice']={key:result[key] for key in ('status','id','test_id') if key in result}
                return redirect(url_for('backups.page'),code=303)
            except StateLockBusy:
                error='A scan or settings operation holds the state lock. Wait for it to finish; no backup retry was queued.';status=409
            except Exception:
                error='Backup operation could not be verified. Partial files may be retained for review. No retry, active restore, or media action was performed.';status=409
        else:
            notice=session.pop('backup_notice',None)
            if isinstance(notice,dict) and notice.get('status') in MESSAGES:
                identifier=notice.get('test_id') or notice.get('id')
                if isinstance(identifier,str) and re.fullmatch('[0-9a-f]{32}',identifier):
                    message=MESSAGES[notice['status']]+' Reference: '+identifier
        try:
            if set(request.args)-{'page'} or len(request.args.getlist('page'))>1:raise ValueError()
            page_text=request.args.get('page','1')
            if not re.fullmatch('[1-9][0-9]?',page_text):raise ValueError()
            page_number=int(page_text)
            if page_number>20:raise ValueError()
        except ValueError:return 'Invalid backup page.',400
        unavailable=False
        try:listing=workspace.inventory(config_file=config_file,page=page_number)
        except Exception:
            unavailable=True;listing=None
            if status==200:status=503
        return render_template('backups.html',listing=listing,unavailable=unavailable,message=message,error=error,
            csrf=session['backup_csrf'],display_time=display_time),status

    return bp
