import os

from app.sqlite_scheduled_paths import scan_held_directory


def test_independent_scan_reads_all_names_without_disturbing_active_cursor(tmp_path):
    for name in ('A', 'B', 'C'):
        (tmp_path / name).mkdir()
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with os.scandir(fd) as active:
            first = next(active).name
            position = os.lseek(fd, 0, os.SEEK_CUR)
            with scan_held_directory(fd) as entries:
                assert {entry.name for entry in entries} == {'A', 'B', 'C'}
            assert os.lseek(fd, 0, os.SEEK_CUR) == position
            assert {first} | {entry.name for entry in active} == {'A', 'B', 'C'}
    finally:
        os.close(fd)


def test_fresh_stream_sees_addition_after_prior_scan(tmp_path):
    (tmp_path / 'A').mkdir()
    fd = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with scan_held_directory(fd) as entries:
            assert {entry.name for entry in entries} == {'A'}
        (tmp_path / 'B').mkdir()
        with scan_held_directory(fd) as entries:
            assert {entry.name for entry in entries} == {'A', 'B'}
    finally:
        os.close(fd)
