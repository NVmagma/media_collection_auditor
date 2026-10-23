import io
import tarfile

import pytest

from scripts import sqlite_controller_runtime_prepare as runtime


def lab(tmp_path, entries):
    root=tmp_path.resolve()
    (root/'.disposable_controller_runtime').write_bytes(runtime.MARKER)
    with tarfile.open(root/'image.tar','w') as archive:
        for name,kind,payload in entries:
            entry=tarfile.TarInfo(name)
            if kind=='file':
                entry.size=len(payload);entry.mode=0o755
                archive.addfile(entry,io.BytesIO(payload))
            else:
                entry.type=tarfile.SYMTYPE if kind=='symlink' else tarfile.CHRTYPE
                entry.linkname=payload
                archive.addfile(entry)
    return root


def test_contained_runtime_prepared_without_execution(tmp_path):
    root=lab(tmp_path,[('usr/local/bin/python3.12','file',b'not executed'),
                       ('usr/local/bin/python3','symlink','/usr/local/bin/python3.12')])
    result=runtime.prepare(root)
    assert result['production_authorized'] is False
    assert (root/'rootfs/usr/local/bin/python3').read_bytes()==b'not executed'
    assert (root/'rootfs/controller-smoke.py').read_bytes()==runtime.SMOKE
    with pytest.raises(FileExistsError):runtime.prepare(root)


@pytest.mark.parametrize('entries',[
    [('../escape','file',b'no')],
    [('/absolute','file',b'no')],
    [('out','symlink','../../escape'),('out/payload','file',b'no')],
    [('device','device','')],
])
def test_archive_cannot_escape_or_create_devices(tmp_path,entries):
    root=lab(tmp_path,entries)
    with pytest.raises((tarfile.FilterError,RuntimeError)):
        runtime.prepare(root)
    assert not (root.parent/'escape').exists()
    assert not (root/'rootfs/controller-smoke.py').exists()


def test_expansion_limit_retains_partial_artifacts(tmp_path,monkeypatch):
    root=lab(tmp_path,[('large','file',b'x'*10)])
    monkeypatch.setattr(runtime,'MAX_ENTRIES',0)
    with pytest.raises(RuntimeError,match='expansion exceeds'):
        runtime.prepare(root)
    assert (root/'rootfs').is_dir()


def test_missing_marker_never_extracts(tmp_path):
    root=tmp_path.resolve()
    with pytest.raises(FileNotFoundError):runtime.prepare(root)
    assert not (root/'rootfs').exists()


def test_missing_interpreter_never_reports_prepared(tmp_path):
    root=lab(tmp_path,[('unrelated','file',b'not Python')])
    with pytest.raises(FileNotFoundError):runtime.prepare(root)
    assert not (root/'rootfs/controller-smoke.py').exists()
