"""Browser administrator import flow. Integration tokens never grant writes."""
import hmac
import math
import re
import secrets
from time import time
from urllib.parse import urlsplit
from flask import Blueprint, request, session, render_template

from app import arr_import_service as service
from app.arr_import_transport import ArrImportError
from app.state_lock import StateLockBusy

MESSAGES = {
    'selection_invalid': 'Choose an existing folder, provider match and quality profile.',
    'no_pending_import': 'No pending Arr import was found. Other operation types require their own recovery.',
    'unsafe_folder': 'The folder contains an unsafe entry or is not a supported library folder.',
    'already_managed_or_conflicting': 'This provider ID or folder already exists in Arr. Review its existing record.',
    'review_changed': 'The reviewed folder, tracking or profile changed. Prepare a new review.',
    'quality_profile_changed': 'Choose a currently available quality profile.',
    'arr_root_unavailable': 'The current stage root must be configured and accessible in Arr.',
    'arr_version_unsupported': 'This import flow supports Sonarr 4 and Radarr 6.',
    'no_existing_media': 'The selected folder contains no supported media files.',
    'pending_operation': 'An operation is pending. Resolve it before importing.',
    'provider_match_unavailable': 'Choose a unique provider match before importing.',
}


def create_blueprint(*, is_admin):
    bp = Blueprint('arr_imports', __name__)

    @bp.before_request
    def admin_only():
        if not is_admin(): return {'ok': False, 'message': 'Administrator access required.'}, 403
        if request.method == 'POST':
            origin = request.headers.get('Origin')
            data = request.get_json(silent=True)
            token = data.get('csrf') if isinstance(data, dict) else None
            if (not origin or urlsplit(origin).netloc != request.host
                    or not isinstance(token, str) or not session.get('arr_import_csrf')
                    or not hmac.compare_digest(token.encode(), session['arr_import_csrf'].encode())):
                return {'ok': False, 'message': 'Invalid request. Reload the import page.'}, 403

    @bp.after_request
    def no_cache(response):
        response.headers['Cache-Control'] = 'no-store'
        return response

    @bp.get('/arr-imports')
    def page():
        session.setdefault('arr_import_csrf', secrets.token_urlsafe(32))
        return render_template('arr-imports.html', csrf=session['arr_import_csrf'])

    def respond(action, *, mutation=False):
        try: return {'ok': True, **action()}
        except StateLockBusy:
            return {'ok': False, 'message': 'A scan or settings operation holds the worker lock. Try again when it finishes.'}, 409
        except Exception as error:
            code = error.args[0] if isinstance(error, ArrImportError) and error.args else None
            message = MESSAGES.get(code, 'Import review unavailable. Check Arr connectivity, folder and binding settings.')
            if mutation:
                message = ((MESSAGES[code] + ' ') if code in MESSAGES else '') + ('Import did not finish with a verified result. A pending intent may remain. '
                           'Use Verify pending import before trying another import.')
            return {'ok': False, 'message': message, 'automatic_retry': False}, 409

    @bp.get('/api/arr-import/options')
    def options():
        return respond(lambda: service.options(library=request.args.get('library')))

    @bp.get('/api/arr-import/lookup')
    def lookup():
        return respond(lambda: service.lookup(library=request.args.get('library'), term=request.args.get('term')))

    def selection(data):
        return {key: data[key] for key in ('library', 'folder', 'provider_id', 'quality_profile_id')}

    def current_draft(draft, fingerprint):
        return (isinstance(draft, dict) and isinstance(fingerprint, str)
            and re.fullmatch('[0-9a-f]{64}', fingerprint)
            and isinstance(draft.get('fingerprint'), str)
            and hmac.compare_digest(fingerprint, draft['fingerprint'])
            and type(draft.get('at')) in (int, float) and math.isfinite(draft['at'])
            and 0 <= time() - draft['at'] <= 600)

    @bp.post('/api/arr-import/review')
    def review():
        data = request.get_json()
        if set(data) != {'csrf', 'library', 'folder', 'provider_id', 'quality_profile_id'}:
            return {'ok': False, 'message': 'Invalid selection.'}, 400
        def run():
            chosen = selection(data)
            report = service.review(selection=chosen)
            session['arr_import_review'] = {'selection': chosen,
                'fingerprint': report['review_fingerprint'], 'at': time()}
            return report
        return respond(run)

    @bp.post('/api/arr-import/apply')
    def apply():
        data = request.get_json()
        draft = session.get('arr_import_review')
        if (set(data) != {'csrf', 'review_fingerprint'}
                or not current_draft(draft, data.get('review_fingerprint'))
                or not isinstance(draft.get('selection'), dict)):
            return {'ok': False, 'message': 'Prepare a new import review.'}, 409
        # Consume browser consent for this attempt even if its acknowledgment is lost.
        session.pop('arr_import_review', None)
        return respond(lambda: service.apply(selection=draft['selection'],
            expected_fingerprint=draft['fingerprint']), mutation=True)

    @bp.post('/api/arr-import/recovery-review')
    def recovery_review():
        if set(request.get_json()) != {'csrf'}:
            return {'ok': False, 'message': 'Invalid request.'}, 400
        def run():
            report = service.recover()
            session['arr_import_recovery'] = {'fingerprint': report['review_fingerprint'], 'at': time()}
            return report
        return respond(run)

    @bp.post('/api/arr-import/recovery-apply')
    def recovery_apply():
        data, draft = request.get_json(), session.get('arr_import_recovery')
        if (set(data) != {'csrf', 'review_fingerprint'}
                or not current_draft(draft, data.get('review_fingerprint'))):
            return {'ok': False, 'message': 'Verify the pending import first.'}, 409
        session.pop('arr_import_recovery', None)
        return respond(lambda: service.recover(expected_fingerprint=draft['fingerprint']), mutation=True)

    return bp
