import pytest

from app.sqlite_control_location_review import LocationReviewError, review_control_location


def review(paths, exposures):
    return review_control_location(candidate_paths=paths, exposures=exposures)


@pytest.mark.parametrize('kind', ['nfs_export', 'smb_share', 'container_bind'])
def test_parent_exposure_including_readonly_container_visibility(kind):
    result = review(['/mnt/user/appdata/controller'], [{'kind': kind, 'path': '/mnt/user/appdata'}])
    assert result['conflicts'][0]['relationship'] == 'candidate_within_exposure'
    assert 'observed_exposure_overlap' in result['blockers']
    assert result['private_location_verified'] is False


def test_supplied_native_and_user_share_aliases_are_both_checked():
    result = review(['/mnt/media/control', '/mnt/user/control'],
                    [{'kind': 'nfs_export', 'path': '/mnt/user/control'}])
    assert len(result['conflicts']) == 1
    assert result['conflicts'][0]['candidate_path'] == '/mnt/user/control'


def test_component_boundaries_do_not_confuse_sibling_names():
    result = review(['/mnt/user/appdata-private'],
                    [{'kind': 'nfs_export', 'path': '/mnt/user/appdata'}])
    assert result['conflicts'] == []
    assert result['private_location_verified'] is False
    assert 'alias_and_exposure_coverage_unverified' in result['blockers']


def test_nested_exposure_conflicts_and_inputs_remain_unchanged():
    paths = ['/control']; exposures = [{'kind': 'container_bind', 'path': '/control/requests'}]
    result = review(paths, exposures)
    assert result['conflicts'][0]['relationship'] == 'exposure_within_candidate'
    assert paths == ['/control']
    assert exposures == [{'kind': 'container_bind', 'path': '/control/requests'}]


@pytest.mark.parametrize('path', ['relative', '/a/../b', '/a//b', '//a', '/a/', '/a/./b', '/a\n', '/a\\b'])
def test_ambiguous_paths_are_not_normalized_into_acceptance(path):
    with pytest.raises(LocationReviewError):
        review([path], [])


def test_empty_inventory_never_authorizes_anything():
    result = review(['/control'], [])
    assert result['production_authorized'] is False
    assert result['production_activation'] == 'disabled'
    assert result['automatic_action'] == 'none'
    assert result['status'] == 'review_required'


@pytest.mark.parametrize('exposures', [[{'kind': 'unknown', 'path': '/a'}],
                                      [{'kind': 'nfs_export', 'path': '/a', 'complete': True}],
                                      [{'kind': 'nfs_export', 'path': 'relative'}], None])
def test_malformed_inventory_rejected(exposures):
    with pytest.raises(LocationReviewError):
        review(['/control'], exposures)
