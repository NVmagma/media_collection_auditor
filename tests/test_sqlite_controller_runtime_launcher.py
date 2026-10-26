import os
from pathlib import Path
import shlex
import subprocess


SCRIPT=Path(__file__).resolve().parents[1]/'scripts/sqlite_controller_runtime_lab.sh'


def executable(directory,name,body):
    path=directory/name
    path.write_text('#!/bin/sh\n'+body+'\n')
    path.chmod(0o700)


def test_mutable_image_rejected_before_docker_or_lab_creation(tmp_path):
    commands=tmp_path/'bin';commands.mkdir()
    called=tmp_path/'unexpected-docker'
    executable(commands,'uname','echo Linux')
    executable(commands,'id','echo 0')
    executable(commands,'realpath','for value do :; done; printf "%s\\n" "$value"')
    for name in ('docker','unshare','chroot'):
        executable(commands,name,'touch '+shlex.quote(str(called))+'; exit 99')
    base=tmp_path/'labs';base.mkdir()
    env={**os.environ,'PATH':str(commands)+os.pathsep+os.defpath,
         'SQLITE_LAB_IMAGE':'python:3.12-slim'}
    result=subprocess.run(['/bin/bash',str(SCRIPT),str(base)],env=env,capture_output=True,text=True)
    assert result.returncode!=0
    assert 'Immutable reviewed image digest required' in result.stderr
    assert not called.exists()
    assert list(base.iterdir())==[]


def test_non_linux_host_never_contacts_docker(tmp_path):
    commands=tmp_path/'bin';commands.mkdir()
    called=tmp_path/'unexpected-docker'
    executable(commands,'uname','echo Darwin')
    executable(commands,'docker','touch '+shlex.quote(str(called))+'; exit 99')
    result=subprocess.run(['/bin/bash',str(SCRIPT),str(tmp_path)],
        env={**os.environ,'PATH':str(commands)+os.pathsep+os.defpath},
        capture_output=True,text=True)
    assert result.returncode!=0
    assert 'Linux host' in result.stderr
    assert not called.exists()
