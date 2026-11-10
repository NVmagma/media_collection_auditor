"""Keep failure stages in history without saving raw errors or private paths."""
from app.failure_diagnostics import clean_failure_details,failure_details
from app.json_worker_service import JSONWorkerService


def test_returned_worker_failure_is_saved_in_history(capsys):
    saved=[]
    def execute(*args,**kwargs):
        return dict(result='failed',failure_stage='collection',error_type='RuntimeError',
            failure_sites=[{'file':'json_readonly_scan.py','line':214}],
            error='private credentials must not be copied',decisions=(),completed_moves=())
    worker=JSONWorkerService(execute=execute,load_settings=lambda:{'DRY_RUN':'true'},record=saved.append)
    record=worker.run_once(trigger='scheduled')
    assert record['failure_stage']=='collection' and record['error_type']=='RuntimeError'
    assert record['failure_sites']==[{'file':'json_readonly_scan.py','line':214}]
    assert 'private credentials' not in str(record)
    assert saved[0]['failure_stage']=='collection'
    assert record['discovery_changes'] is None
    output=capsys.readouterr().out
    assert 'collection' in output and 'RuntimeError' in output
    assert 'private credentials' not in output


def test_unrecognized_fields_and_paths_are_not_saved():
    details=clean_failure_details(dict(failure_stage='private/path',error_type='URL: secret',
        failure_sites=[{'file':'/private/secrets.py','line':12},{'file':'web.py','line':True}],
        error='private response'))
    assert details==dict(failure_stage=None,error_type=None,failure_sites=[])


def test_exception_text_is_never_part_of_diagnostics():
    try: raise ValueError('private-server-url and token')
    except ValueError as error: details=failure_details(error,'collection')
    assert details['error_type']=='ValueError'
    assert details['failure_sites']==[]
    assert 'private-server-url' not in str(details)


def test_invalid_stage_type_does_not_break_error_reporting():
    assert clean_failure_details({'failure_stage':{'private':'value'}})['failure_stage'] is None
