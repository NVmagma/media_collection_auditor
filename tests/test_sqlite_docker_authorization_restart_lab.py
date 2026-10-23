"""Orchestrator safety/cleanup tests; fake Docker commands are not daemon evidence."""
from types import SimpleNamespace
import pytest
from scripts.sqlite_docker_authorization_restart_lab import run_lab

HOST = 'unix:///private/disposable-docker.sock'
IMAGE = 'sha256:' + '1' * 64


@pytest.mark.parametrize('host,image', [('tcp://tower:2375',IMAGE), (HOST,'docker:latest')])
def test_remote_targets_and_mutable_images_rejected_without_commands(monkeypatch, host, image):
    monkeypatch.setattr('subprocess.run', lambda *a, **k: pytest.fail('No Docker calls'))
    with pytest.raises(ValueError):
        run_lab(host=host, daemon_image=image, python_image=IMAGE)


@pytest.mark.parametrize('fail_client', [False, True])
def test_only_new_isolated_resources_are_controlled_and_cleaned(monkeypatch, fail_client):
    calls=[]
    def fake(command, **kwargs):
        assert kwargs['timeout'] <= 45
        assert command[:3] == ['docker','--host',HOST]
        calls.append(command[3:])
        args=command[3:]
        output='fixture'
        if args[0]=='info': output='Docker Desktop'
        if args[0]=='logs': output='failed to validate authorization plugin'
        if args[0]=='exec':
            if args[-1].endswith('.is_socket())'): output='True'
            elif args[-1].endswith('s.close()'): output='HTTP/1.0 200 OK'
            else: output='{"fixture_only":true}'
        if args[0]=='run' and '--rm' in args:
            if fail_client:
                return SimpleNamespace(returncode=1,stdout='',stderr='fixture failure')
            output='{"fixture_only":true}'
        if args[0]=='inspect':
            output='false' if 'Running' in args[2] else '1'
        return SimpleNamespace(returncode=0,stdout=output,stderr='')
    monkeypatch.setattr('subprocess.run',fake)
    if fail_client:
        with pytest.raises(RuntimeError,match='fixture failure'):
            run_lab(host=HOST,daemon_image=IMAGE,python_image=IMAGE)
    else:
        result=run_lab(host=HOST,daemon_image=IMAGE,python_image=IMAGE)
        assert result['production_authorized'] is False
        assert result['restart_inhibition_verified'] is False
    runs=[args for args in calls if args[0]=='run']
    assert len(runs)==(3 if fail_client else 4)
    for args in runs:
        assert '--privileged' not in args
        assert args[args.index('--network')+1]=='none'
        assert args[args.index('--cap-drop')+1]=='ALL'
        assert args[args.index('--pull')+1]=='never'
        assert '--publish' not in args and '-p' not in args
        assert not any('src=/var/run/docker.sock' in arg for arg in args)
    daemon=next(args for args in runs if '--cap-add' in args)
    assert [daemon[i+1] for i,arg in enumerate(daemon) if arg=='--cap-add']==['CHOWN','DAC_OVERRIDE']
    removals=[args for args in calls if args[0]=='rm']
    assert len(removals)==(2 if fail_client else 3)
    assert all(args[-1].startswith('mca-authz-') for args in removals)
    assert calls[-1][0:2]==['volume','rm']
    assert not any(args[0] in ('pull','build','system','prune') for args in calls)


def test_unraid_outer_daemon_rejected_before_creating_resources(monkeypatch):
    calls=[]
    def fake(command, **kwargs):
        calls.append(command[3:])
        return SimpleNamespace(returncode=0, stdout='Unraid', stderr='')
    monkeypatch.setattr('subprocess.run',fake)
    with pytest.raises(RuntimeError,match='do not run on Tower'):
        run_lab(host=HOST,daemon_image=IMAGE,python_image=IMAGE)
    assert calls == [['info','--format','{{.OperatingSystem}}']]
