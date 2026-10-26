import json
from pathlib import Path
import subprocess
import sys

import pytest

from scripts import sqlite_host_controller_bundle as bundle


def test_exact_stdlib_bundle_has_no_app_dependencies_or_installation(tmp_path):
    root=tmp_path.resolve()/'bundle'
    result=bundle.build(root)
    assert result['service_controls_included'] is False
    assert result['installation_authorized'] is False
    assert set(json.loads((root/'bundle.json').read_bytes())['files'])==set((*bundle.MODULES,'controller.py'))
    result=subprocess.run([sys.executable,'-I','-S','-B',str(root/'controller.py'),'--help'],capture_output=True)
    assert result.returncode==0
    assert b'{prepare,review}' in result.stdout
    assert b'activate' not in result.stdout
    with pytest.raises(FileExistsError):bundle.build(root)


@pytest.mark.parametrize('change',['source','manifest','duplicate','symlink'])
def test_changed_bundle_rejected_before_control_directory_creation(tmp_path,change):
    root=tmp_path.resolve()/'bundle'
    bundle.build(root)
    if change=='source':(root/bundle.MODULES[0]).write_bytes(b'raise RuntimeError("must not execute")')
    elif change=='manifest':
        path=root/'bundle.json';manifest=json.loads(path.read_bytes())
        manifest['production_authorized']=True;path.write_text(json.dumps(manifest))
    elif change=='duplicate':(root/'bundle.json').write_text('{"mode":1,"mode":2}')
    else:
        path=root/bundle.MODULES[0];path.rename(root/'retained.py');path.symlink_to(root/'retained.py')
    control=tmp_path.resolve()/'control'
    result=subprocess.run([sys.executable,'-I','-S','-B',str(root/'controller.py'),'prepare','--root',str(control)],capture_output=True)
    assert result.returncode!=0
    assert not control.exists()
    assert b'must not execute' not in result.stderr


@pytest.mark.parametrize('kind',['fifo','hardlink'])
def test_nonregular_or_shared_package_artifacts_fail_without_blocking(tmp_path,kind):
    import os
    root=tmp_path.resolve()/'bundle'
    bundle.build(root)
    target=root/'bundle.json'
    if kind=='fifo':
        target.unlink();os.mkfifo(target)
    else:os.link(target,root/'shared-manifest')
    result=subprocess.run([sys.executable,'-I','-S','-B',str(root/'controller.py'),'prepare',
                           '--root',str(tmp_path.resolve()/'control')],capture_output=True,timeout=10)
    assert result.returncode!=0
    assert not (tmp_path/'control').exists()
