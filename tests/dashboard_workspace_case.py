"""Render synthetic dashboard inputs without reading production state or services."""
from contextlib import ExitStack
from copy import deepcopy
from unittest.mock import patch
import os
os.environ.setdefault('WEB_SESSION_SECRET', 'fixture-dashboard-secret')
import web


def render_workspace(*, admin=False, tracking_available=True, run_updates=None, workspace="Overview", history_records=None):
    state = {'first_seen': {'The Quiet Orbit (2026)': '2026-10-01T11:30:00',
                            'TV/Lantern House (2026)': '2026-10-02T11:30:00',
                            'A & B <Moon> (2026)': '2026-10-03T11:30:00'},
             'queued': {'Summer Frontier (2026)': '2026-10-20T11:30:00'},
             'keep_seen': {}, 'in_removal': {}}
    stages = {name: [] for name in ('Waiting', 'Holding', 'Keep', 'Removal')}
    stages['Waiting'] = [{'library': 'Movies', 'title': 'The Quiet Orbit (2026)', 'since': state['first_seen']['The Quiet Orbit (2026)']},
                         {'library': 'TV', 'title': 'Lantern House (2026)', 'since': state['first_seen']['TV/Lantern House (2026)']}]
    stages['Waiting'].append({'library': 'Movies', 'title': 'A & B <Moon> (2026)', 'since': state['first_seen']['A & B <Moon> (2026)']})
    stages['Holding'] = [{'library': 'Movies', 'title': 'Summer Frontier (2026)', 'since': state['queued']['Summer Frontier (2026)']}]
    stages['Waiting'].append({'library': 'TV', 'title': 'Untracked Series (2026)', 'since': None})
    state['first_seen']['TV/Retained unmatched (2026)'] = '2026-10-01T11:30:00'
    config = {'ENABLE_MOVIES': 'true', 'ENABLE_TV': 'true', 'DRY_RUN': 'true',
              'ALLOW_PERMANENT_DELETE': 'false'}
    run = {'storage_authority': 'sqlite', 'execution_mode': 'scheduled_preview',
           'production_activation': 'preview_only', 'running': False, 'queued': False,
           'status': 'advisory_only', 'last_result': 'completed',
           'movies_processed': None, 'tv_processed': None,
           'last_finished': '2026-10-27T09:04:00+00:00', 'next_run': '2026-10-28T09:00:00+00:00',
           'moves_proposed': 2, 'discovery_changes': 1}
    run['history_scope'] = 'current_process'
    run.update(run_updates or {})
    if history_records is None:
        history_records = []
        for index in range(7):
            record = {'started_at': f'2026-10-{27-index:02}T09:00:00+00:00',
                      'finished_at': f'2026-10-{27-index:02}T09:04:00+00:00',
                      'result': 'completed', 'dry_run': True, 'trigger': 'manual',
                      'result_basis': 'worker_return', 'moves_proposed': 2, 'discovery_changes': 1,
                      'moves_completed': 0, 'arr_completed': 0}
            if index in (1, 4):
                record.update(result='failed', trigger='scheduled', moves_proposed=None,
                              discovery_changes=None, moves_completed=None, arr_completed=None,
                              result_basis='blocked_or_uncertain' if index == 1 else 'observation_unavailable')
            if index == 2:
                record.update(dry_run=False, trigger='scheduled', moves_proposed=None,
                              discovery_changes=None, moves_completed=2, arr_completed=2)
            history_records.append(record)
    with ExitStack() as stack:
        for name, value in {'current_user': {'name': 'Fixture reviewer', 'admin': admin},
                            'load_actions': [], 'load_config': config,
                            'filesystem_stages': (deepcopy(stages), []),
                            '_dashboard_signals': None, 'selected_run_snapshot': run,
                            'selected_run_history': history_records}.items():
            stack.enter_context(patch.object(web, name, return_value=value))
        stack.enter_context(patch.object(web, 'load_state', **({'return_value': state} if tracking_available else
                                                              {'side_effect': RuntimeError('Fixture tracking unavailable')})))
        return web.app.test_client().get('/review' if workspace == 'Review' else '/')


if __name__ == '__main__':
    import sys
    from pathlib import Path
    response = render_workspace(workspace='Review' if len(sys.argv) > 2 and sys.argv[2] == 'Review' else 'Overview')
    assert response.status_code == 200
    Path(sys.argv[1]).write_bytes(response.data)
    Path(sys.argv[1] + '.review.html').write_bytes(render_workspace(workspace='Review').data)
    Path(sys.argv[1] + '.admin.html').write_bytes(render_workspace(admin=True).data)
