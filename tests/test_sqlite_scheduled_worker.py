from copy import deepcopy
from datetime import datetime
from pathlib import Path

import pytest

from app.sqlite_operation_coordinator import INTENTS_KEY
from app.sqlite_scheduled_plan import ScheduledScanBlocked
from app.sqlite_scheduled_worker import configured_scheduled_worker, prepare_scheduled_worker
from app.sqlite_state import SECTIONS

NOW = datetime(2026, 10, 24)
FIELDS = ('transient', 'holding', 'keep', 'removal')


def setup(tmp_path):
    libraries = []
    for name, kind, prefix in [('Movies', 'Movie', ''), ('TV', 'Series', 'TV/')]:
        roots = {}
        for field in FIELDS:
            path = tmp_path / name / field
            path.mkdir(parents=True)
            roots[field] = str(path)
        libraries.append(dict(name=name, jellyfin_type=kind, state_prefix=prefix,
                              wait_days=7, new_content_resets_clock=False, **roots))
    snapshot = {key: {} for key in SECTIONS}
    # Identical folder names in disjoint libraries are different tracking keys.
    for library in libraries:
        (Path(library['transient']) / 'Same (2020)').mkdir()
        snapshot['first_seen'][library['state_prefix'] + 'Same (2020)'] = '2026-01-01'
    return libraries, snapshot


def configure(libraries, **kwargs):
    return configured_scheduled_worker(libraries=libraries, local_time='02:00',
        timezone_name='America/Los_Angeles', holding_days=7, **kwargs)


def prepare(config, snapshot, **kwargs):
    return prepare_scheduled_worker(config=config, snapshot=snapshot, revision=4,
        fetch_signals=kwargs.pop('fetch_signals', lambda binding: {}), now=NOW, **kwargs)


def test_two_libraries_share_one_cap_and_detached_configuration(tmp_path):
    libraries, snapshot = setup(tmp_path)
    config = configure(libraries, maximum_actions=1)
    libraries[0]['transient'] = '/wrong'
    libraries[0]['wait_days'] = 9999
    observed = []
    result = prepare(config, snapshot, fetch_signals=lambda binding: observed.append(binding.media_key) or {})
    assert observed == ['Same (2020)', 'TV/Same (2020)']
    assert result.plan.scanned_titles == 2 and result.plan.capped_moves == 1
    assert len(result.plan.moves) == 1
    assert result.plan.moves[0].library == 'Movies'
    assert result.production_activation == 'disabled' and result.production_authorized is False
    assert result.untracked == ()


def test_later_library_failure_makes_no_decision(tmp_path, monkeypatch):
    libraries, snapshot = setup(tmp_path)
    import app.sqlite_scheduled_plan as planner
    monkeypatch.setattr(planner, 'review_decision', lambda *a, **k: pytest.fail('decision before full scan'))
    def fetch(binding):
        if binding.library == 'TV':
            raise RuntimeError('unavailable')
        return {}
    before = deepcopy(snapshot)
    with pytest.raises(RuntimeError, match='unavailable'):
        prepare(configure(libraries), snapshot, fetch_signals=fetch)
    assert snapshot == before


def test_duplicate_stage_title_blocks_before_protection(tmp_path):
    libraries, snapshot = setup(tmp_path)
    (Path(libraries[1]['holding']) / 'Same (2020)').mkdir()
    with pytest.raises(ScheduledScanBlocked, match='ambiguous_title_location'):
        prepare(configure(libraries), snapshot, fetch_signals=lambda b: pytest.fail('unsafe inventory'))


@pytest.mark.parametrize('change', ['symlink', 'nested', 'same'])
def test_cross_library_root_aliases_rejected(tmp_path, change):
    libraries, snapshot = setup(tmp_path)
    if change == 'symlink':
        alias = tmp_path / 'alias'; alias.symlink_to(libraries[0]['transient'], target_is_directory=True)
        libraries[1]['transient'] = str(alias)
        with pytest.raises(OSError):
            prepare(configure(libraries), snapshot)
    else:
        libraries[1]['transient'] = libraries[0]['transient'] + ('/nested' if change == 'nested' else '')
        with pytest.raises(ValueError, match='disjoint'):
            configure(libraries)


@pytest.mark.parametrize('change', ['add_title', 'replace_root', 'replace_title'])
def test_inventory_mutation_during_collection_blocks_result(tmp_path, change):
    libraries, snapshot = setup(tmp_path)
    root = Path(libraries[0]['transient'])
    def fetch(binding):
        if binding.library == 'TV':
            if change == 'add_title':
                (root / 'New').mkdir()
            elif change == 'replace_root':
                root.rename(root.with_name('old')); root.mkdir()
            else:
                title = root / 'Same (2020)'
                title.rename(root / 'Old'); title.mkdir()
        return {}
    with pytest.raises(ScheduledScanBlocked, match='changed'):
        prepare(configure(libraries), snapshot, fetch_signals=fetch)


def test_untracked_titles_are_reported_without_clock_creation(tmp_path):
    libraries, snapshot = setup(tmp_path)
    snapshot['first_seen'].pop('TV/Same (2020)')
    before = deepcopy(snapshot)
    result = prepare(configure(libraries), snapshot)
    assert result.untracked == ('TV/Same (2020)',)
    assert len(result.plan.moves) == 1
    assert snapshot == before


def test_caller_state_mutation_cannot_change_captured_plan(tmp_path):
    libraries, snapshot = setup(tmp_path)
    def fetch(binding):
        snapshot['first_seen'].clear()
        return {}
    result = prepare(configure(libraries), snapshot, fetch_signals=fetch)
    assert len(result.plan.moves) == 2 and result.untracked == ()


def test_pending_operation_blocks_before_collection(tmp_path):
    libraries, snapshot = setup(tmp_path)
    # Existing planner blocks truthy pending records; no database access here.
    snapshot[INTENTS_KEY] = {'id': 'pending'}
    with pytest.raises((ScheduledScanBlocked, ValueError)):
        prepare(configure(libraries), snapshot, fetch_signals=lambda b: pytest.fail('pending collection'))


def test_missing_protection_yields_no_moves(tmp_path):
    libraries, snapshot = setup(tmp_path)
    assert prepare(configure(libraries), snapshot, fetch_signals=lambda b: None).plan.moves == ()


def test_global_title_limit_includes_both_libraries(tmp_path):
    libraries, snapshot = setup(tmp_path)
    with pytest.raises(ScheduledScanBlocked, match='title_limit'):
        prepare(configure(libraries), snapshot, maximum_titles=1,
                fetch_signals=lambda b: pytest.fail('limit must block before collection'))


def test_total_budget_includes_inventory(tmp_path):
    libraries, snapshot = setup(tmp_path)
    tick = iter(range(100))
    with pytest.raises(ScheduledScanBlocked, match='deadline'):
        prepare(configure(libraries), snapshot, maximum_scan_seconds=2, timer=lambda: next(tick))


@pytest.mark.parametrize('field,value', [('state_prefix', 'Other/'), ('wait_days', True),
    ('new_content_resets_clock', True), ('jellyfin_type', 'Episode')])
def test_unsupported_policy_rejected_before_collection(tmp_path, field, value):
    libraries, snapshot = setup(tmp_path)
    libraries[1][field] = value
    with pytest.raises(ValueError):
        configure(libraries)


def test_real_collector_uses_configured_tags_for_movie_and_series(tmp_path):
    from app.sqlite_scheduled_jellyfin import scheduled_inventory_signal_reader
    libraries, snapshot = setup(tmp_path)
    calls = []
    def fetch(path, params):
        calls.append(path)
        if path == '/Users':
            return [{'Id': 'viewer'}]
        kind = params['IncludeItemTypes']
        return {'TotalRecordCount': 1, 'Items': [{'Id': kind, 'Type': kind,
            'Path': '/media/' + kind + '/Same (2020)' + ('/movie.mkv' if kind == 'Movie' else ''),
            'Tags': ['save'], 'UserData': {'IsFavorite': False, 'Played': False, 'PlayCount': 0}}]}
    tags = {'keep': 'save', 'protected': 'protect-all', 'disliked': 'leave', 'keep_all': 'seasons'}
    reader = scheduled_inventory_signal_reader(fetch=fetch, tag_names=tags, clock=lambda: NOW)
    tags['keep'] = 'changed'
    result = prepare(configure(libraries), snapshot, fetch_signals=reader)
    assert [move.destination_stage for move in result.plan.moves] == ['Keep', 'Keep']
    assert calls == ['/Users', '/Users/viewer/Items'] * 2


def test_real_collector_incomplete_coverage_produces_no_candidate(tmp_path):
    from app.sqlite_scheduled_jellyfin import scheduled_inventory_signal_reader
    libraries, snapshot = setup(tmp_path)
    reader = scheduled_inventory_signal_reader(fetch=lambda *a: [], clock=lambda: NOW)
    assert prepare(configure(libraries), snapshot, fetch_signals=reader).plan.moves == ()
