"""Render synthetic dashboard inputs without reading production state or services."""
from contextlib import ExitStack
from copy import deepcopy
from unittest.mock import patch
import os
os.environ.setdefault('WEB_SESSION_SECRET', 'fixture-dashboard-secret')
import web


def render_workspace(*, admin=False, tracking_available=True):
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
    config = {'ENABLE_MOVIES': 'true', 'ENABLE_TV': 'true', 'DRY_RUN': 'true',
              'ALLOW_PERMANENT_DELETE': 'false'}
    run = {'storage_authority': 'sqlite', 'execution_mode': 'scheduled_preview',
           'production_activation': 'preview_only', 'running': False, 'queued': False,
           'status': 'advisory_only', 'last_result': 'completed',
           'movies_processed': None, 'tv_processed': None}
    with ExitStack() as stack:
        for name, value in {'current_user': {'name': 'Fixture reviewer', 'admin': admin},
                            'load_actions': [], 'load_config': config,
                            'filesystem_stages': (deepcopy(stages), []),
                            '_dashboard_signals': None, 'selected_run_snapshot': run,
                            'selected_run_history': []}.items():
            stack.enter_context(patch.object(web, name, return_value=value))
        stack.enter_context(patch.object(web, 'load_state', **({'return_value': state} if tracking_available else
                                                              {'side_effect': RuntimeError('Fixture tracking unavailable')})))
        return web.app.test_client().get('/')


if __name__ == '__main__':
    import sys
    from pathlib import Path
    response = render_workspace()
    assert response.status_code == 200
    Path(sys.argv[1]).write_bytes(response.data)
