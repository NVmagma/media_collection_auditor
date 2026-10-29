from copy import deepcopy
import hashlib
import os
from pathlib import Path
import pytest
from tests.test_unraid_update_candidate_review import ready
from scripts import unraid_update_candidate_review as review
from scripts import unraid_update_candidate_execute as execute
from scripts.sqlite_preview_service_fixture import Engine


@pytest.fixture
def selected(ready):
    case,options=ready
    reference='ghcr.io/nvmagma/media_collection_auditor@sha256:'+'d'*64
    options['image']['RepoDigests']=[reference]
    report=review.review_candidate(**options,reference=reference)
    folder=case.root/'templates';folder.mkdir(mode=0o700)
    for name,raw in options['templates']():(folder/name).write_bytes(raw)
    engine=Engine(options['live']);engine.containers={options['live']['Id']:deepcopy(options['live'])}
    engine.selected_image=deepcopy(options['image'])
    engine.on_create=lambda item:item.update(Image=engine.selected_image['Id'])
    args=dict(engine=engine,review=options['output'],review_identity=options['output_identity'],
        review_fingerprint=hashlib.sha256((options['output']/'review-complete.json').read_bytes()).hexdigest(),
        backup=case.backup,backup_identity=options['backup_identity'],backup_fingerprint=case.fingerprint,
        logs=case.logs,control=case.control,old_logs=case.source.parent,old_control=case.old_control,templates=folder)
    yield case,args,engine


def test_read_only_preflight_has_no_external_actions_or_file_changes(selected):
    case,args,engine=selected
    before={path:path.read_bytes() for path in args['review'].iterdir()}
    update=execute.SelectedUpdate(**args)
    assert execute.run_selected(update,action='check',parent=None)['status']=='candidate_handoff_preflight_verified'
    assert engine.calls==[] and {path:path.read_bytes() for path in args['review'].iterdir()}==before
    case.unchanged()


def test_real_inputs_handoff_and_explicit_recovery_preserve_originals(selected,monkeypatch):
    case,args,engine=selected
    monkeypatch.setattr(execute,'verify_http_health',lambda **kwargs:None)
    update=execute.SelectedUpdate(**args);fd=os.open(args['review'],os.O_RDONLY|os.O_DIRECTORY)
    original=(args['templates']/update.template_name).read_bytes()
    try:
        result=execute.run_selected(update,action='deploy',parent=fd)
        assert result['status']=='candidate_preview_update_complete'
        assert (args['templates']/update.template_name).read_bytes()==update.xml
        # New controller instance represents explicit recovery after process exit.
        recovery=execute.SelectedUpdate(**args)
        restored=execute.run_selected(recovery,action='recover',parent=fd)
        assert restored['status']=='candidate_update_original_recovered'
        assert (args['templates']/update.template_name).read_bytes()==original
        assert engine.inspect(update.captured['Id'])['State']['Running']
        case.unchanged()
    finally:os.close(fd)


@pytest.mark.parametrize('change',['settings','tracking','template','payload','image'])
def test_changed_inputs_block_before_stopping_current(selected,change):
    case,args,engine=selected
    if change=='settings':case.saved.write_text('{}')
    elif change=='tracking':case.source.write_text('{}')
    elif change=='template':next(args['templates'].iterdir()).write_text('<Container/>')
    elif change=='payload':(args['review']/'proposed-container.json').write_text('{}')
    else:engine.selected_image['Id']='sha256:'+'f'*64
    with pytest.raises((RuntimeError,ValueError,KeyError)):
        update=execute.SelectedUpdate(**args);execute.run_selected(update,action='check',parent=None)
    assert engine.calls==[]


def test_corrupt_handoff_journal_blocks_recovery_before_service_action(selected,monkeypatch):
    case,args,engine=selected;monkeypatch.setattr(execute,'verify_http_health',lambda **kwargs:None)
    update=execute.SelectedUpdate(**args);fd=os.open(args['review'],os.O_RDONLY|os.O_DIRECTORY)
    try:
        execute.run_selected(update,action='deploy',parent=fd)
        (args['review']/'service-0001.json').write_text('{}');before=list(engine.calls)
        with pytest.raises(RuntimeError):execute.run_selected(execute.SelectedUpdate(**args),action='recover',parent=fd)
        assert engine.calls==before
    finally:os.close(fd)


@pytest.mark.parametrize('operation',['stop','rename','create','start'])
def test_adapter_lost_ack_keeps_durable_intent_and_never_replays(selected,operation,monkeypatch):
    _,args,engine=selected;monkeypatch.setattr(execute,'verify_http_health',lambda **kwargs:None)
    update=execute.SelectedUpdate(**args);engine.lose_ack=operation
    fd=os.open(args['review'],os.O_RDONLY|os.O_DIRECTORY)
    try:
        with pytest.raises(TimeoutError):execute.run_selected(update,action='deploy',parent=fd)
        assert (args['review']/'service-request.json').exists()
        before=list(engine.calls)
        with pytest.raises((RuntimeError,FileExistsError)):execute.run_selected(update,action='deploy',parent=fd)
        assert engine.calls==before
    finally:os.close(fd)


def test_adapter_recovers_lost_stop_ack_without_adopting_a_replacement(selected,monkeypatch):
    _,args,engine=selected;monkeypatch.setattr(execute,'verify_http_health',lambda **kwargs:None)
    update=execute.SelectedUpdate(**args);engine.lose_ack='stop'
    fd=os.open(args['review'],os.O_RDONLY|os.O_DIRECTORY)
    try:
        with pytest.raises(TimeoutError):execute.run_selected(update,action='deploy',parent=fd)
        engine.lose_ack=None
        report=execute.run_selected(execute.SelectedUpdate(**args),action='recover',parent=fd)
        assert report['status']=='candidate_update_original_recovered'
        assert not report['replacement_container_retained']
    finally:os.close(fd)


def test_lost_create_ack_requires_exact_reviewed_id(selected,monkeypatch):
    _,args,engine=selected;monkeypatch.setattr(execute,'verify_http_health',lambda **kwargs:None)
    update=execute.SelectedUpdate(**args);engine.lose_ack='create'
    fd=os.open(args['review'],os.O_RDONLY|os.O_DIRECTORY)
    try:
        with pytest.raises(TimeoutError):execute.run_selected(update,action='deploy',parent=fd)
        before=list(engine.calls);engine.lose_ack=None
        with pytest.raises(RuntimeError):execute.run_selected(execute.SelectedUpdate(**args),action='recover',parent=fd)
        assert engine.calls==before
        from scripts.sqlite_preview_service_fixture import NEW_ID
        report=execute.run_selected(execute.SelectedUpdate(**args),action='recover',parent=fd,reviewed_new_id=NEW_ID)
        assert report['status']=='candidate_update_original_recovered'
    finally:os.close(fd)


def test_changed_candidate_settings_after_update_block_recovery(selected,monkeypatch):
    case,args,engine=selected;monkeypatch.setattr(execute,'verify_http_health',lambda **kwargs:None)
    update=execute.SelectedUpdate(**args);fd=os.open(args['review'],os.O_RDONLY|os.O_DIRECTORY)
    try:
        execute.run_selected(update,action='deploy',parent=fd)
        (case.logs/'auditor_config.json').write_text('{}');before=list(engine.calls)
        with pytest.raises(RuntimeError):execute.run_selected(execute.SelectedUpdate(**args),action='recover',parent=fd)
        assert engine.calls==before
    finally:os.close(fd)
