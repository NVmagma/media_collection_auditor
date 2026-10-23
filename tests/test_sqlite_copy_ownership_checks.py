"""Run the focused launcher against an inert Docker command, never a daemon."""
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

LAUNCHER=Path(__file__).parents[1]/'scripts/sqlite_copy_ownership_checks.sh'


@pytest.mark.parametrize('run_status',[0,23])
def test_launcher_mounts_only_new_labs_and_selected_readonly_sources(tmp_path,run_status):
    tools=tmp_path/'bin'
    tools.mkdir()
    calls=tmp_path/'calls'
    docker=tools/'docker'
    docker.write_text('#!'+sys.executable+'''\nimport json,os,sys
with open(os.environ['DOCKER_CALLS'],'a') as output:
    output.write(json.dumps(sys.argv[1:])+'\\n')
if sys.argv[1]=='run': sys.exit(int(os.environ['RUN_STATUS']))
''')
    docker.chmod(0o755)
    for name,body in {'uname':'echo Linux','readlink':'shift; printf "%s\\n" "$1"'}.items():
        tool=tools/name
        tool.write_text('#!/bin/sh\n'+body+'\n')
        tool.chmod(0o755)
    first,second=tmp_path/'first',tmp_path/'second'
    first.mkdir();second.mkdir()
    result=subprocess.run(['bash',str(LAUNCHER),str(first),str(second)],
        text=True,capture_output=True,timeout=10,
        env={**os.environ,'PATH':str(tools)+os.pathsep+os.environ['PATH'],
             'DOCKER_CALLS':str(calls),'RUN_STATUS':str(run_status)})
    assert result.returncode==run_status
    operations=[json.loads(line) for line in calls.read_text().splitlines()]
    assert len(operations)==2
    assert operations[0][:2]==['image','inspect']
    run=operations[1]
    assert run[0]=='run' and '--rm' in run and '--read-only' in run
    mounts=[run[index+1] for index,arg in enumerate(run) if arg=='--mount']
    assert len(mounts)==5
    repo=LAUNCHER.parents[1]
    for name in ('app','tests','requirements.txt'):
        assert f'type=bind,src={repo/name},dst=/src/{name},readonly' in mounts
    for parent,target in ((first,'/lab-first'),(second,'/lab-second')):
        labs=list(parent.iterdir())
        assert len(labs)==1 and labs[0].name.startswith('copy-ownership.')
        assert f'type=bind,src={labs[0]},dst={target}' in mounts
    assert run[run.index('--cap-drop')+1]=='ALL'
    assert '240s' in run
    assert '/tmp:rw,noexec,nosuid,nodev,size=256m' in run
    assert '/tmp/testenv/bin/python -m pip install' in run[-1]
    assert '/tmp/testenv/bin/pip ' not in run[-1]
    assert not any('docker.sock' in mount or 'dst=/media,' in mount or '.env' in mount for mount in mounts)
    assert '--publish' not in run and '--privileged' not in run


def test_pip_module_runs_when_generated_launcher_is_not_executable(tmp_path):
    environment=tmp_path/'testenv'
    subprocess.run([sys.executable,'-m','venv',str(environment)],check=True,
                   capture_output=True,text=True,timeout=30)
    launcher=environment/'bin'/'pip'
    launcher.chmod(0o600)
    assert not os.access(launcher,os.X_OK)
    interpreter=environment/'bin'/'python'
    assert interpreter.is_symlink()  # resolves to the executable base runtime
    result=subprocess.run([str(interpreter),'-m','pip','--version'],
                          capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr
    assert 'pip ' in result.stdout
    assert str(environment) in result.stdout
