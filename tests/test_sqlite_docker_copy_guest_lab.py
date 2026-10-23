from pathlib import Path
import pytest
from scripts import sqlite_docker_copy_guest_lab as guest


def test_wrong_guest_blocks_before_media_or_journal_access(monkeypatch):
    monkeypatch.setattr(guest, 'require_guest', lambda: (_ for _ in ()).throw(RuntimeError('wrong guest')))
    monkeypatch.setattr(Path, 'read_bytes', lambda *a: pytest.fail('No media reads'))
    monkeypatch.setattr(guest.journal, 'create_disposable_journal', lambda *a, **k: pytest.fail('No journal'))
    with pytest.raises(RuntimeError, match='wrong guest'):
        guest.run_copy_case('/tmp/absent', lambda: pytest.fail('No observer'))


def test_unmarked_writer_blocks_before_creating_copy_tree(monkeypatch, tmp_path):
    monkeypatch.setattr(guest, 'require_guest', lambda: None)
    (tmp_path/'.disposable_writer').write_bytes(b'NOT A LAB\n')
    with pytest.raises(RuntimeError, match='Marked guest writer'):
        guest.run_copy_case(tmp_path, lambda: pytest.fail('No observer'))
    assert sorted(p.name for p in tmp_path.iterdir()) == ['.disposable_writer']
