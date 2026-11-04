import pytest

from app.filesystem_paths import hold_scheduled_paths, review_scheduled_paths


def roots(tmp_path):
    result = {}
    for stage in ('Waiting', 'Holding', 'Removal', 'Keep'):
        path = tmp_path / stage; path.mkdir(); result[stage] = str(path)
    (tmp_path / 'Waiting/Movie').mkdir()
    return result


def test_parent_symlink_is_rejected_without_following_title(tmp_path):
    configured = roots(tmp_path)
    alias = tmp_path / 'alias'; alias.symlink_to(tmp_path / 'Waiting', target_is_directory=True)
    configured['Waiting'] = str(alias)
    report = review_scheduled_paths(stage_roots=configured, source_stage='Waiting',
        destination_stage='Holding', title_folder='Movie')
    assert report['status'] == 'blocked'
    assert report['production_authorized'] is False


def test_nested_stage_roots_rejected_before_open(tmp_path):
    configured = roots(tmp_path); configured['Holding'] = configured['Waiting'] + '/nested'
    with pytest.raises(ValueError, match='Overlapping'):
        with hold_scheduled_paths(stage_roots=configured, source_stage='Waiting',
                destination_stage='Holding', title_folder='Movie'):
            pytest.fail('Overlapping paths accepted')


@pytest.mark.parametrize('folder', ['../Movie', 'Movie/Other', '.', '/absolute', 'Movie\n'])
def test_unsafe_folder_refused(tmp_path, folder):
    report = review_scheduled_paths(stage_roots=roots(tmp_path), source_stage='Waiting',
        destination_stage='Holding', title_folder=folder)
    assert report['status'] == 'blocked'
