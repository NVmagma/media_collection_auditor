"""Run enabled season retention while holding the JSON scan session."""
import os
from time import monotonic

from app.filesystem_paths import _open_directory
from app.json_scan_control import KEY
from app.sonarr_season_monitoring import SonarrSeasonMonitoring
from app.tv_season_move import move_season
from app.tv_season_delete import delete_season, eligible_for_deletion, expired_season
from app.tv_season_deletion_policy import validate_season_deletion
from app.tv_season_policy import ARCHIVE
from app.tv_season_review import inspect_show


def apply_season_plans(attempt, *, titles, slots, settings, read_settings, completed, deleted, now):
    session = attempt.session
    archive = session.state.get(ARCHIVE, {})
    staged_titles = {key.split('/')[1] for key in archive if key.count('/') == 2}
    candidates = sorted(set(titles), key=lambda title: (title not in staged_titles, title.casefold(), title))

    def verify_settings():
        if read_settings() != settings:
            raise RuntimeError('Season settings changed during scan')

    # One season per show per scan. Staged shows get first use of the remaining slots.
    deletion_enabled = validate_season_deletion(settings)
    deadline = monotonic() + 180
    for title in candidates:
        if slots <= 0 or monotonic() >= deadline:
            break
        verify_settings()
        try:
            initial = inspect_show(title, read_settings, lambda: session.state)
            plan = initial['plan']
            expired = [
                number for number in initial['staged']
                if deletion_enabled and not deleted and eligible_for_deletion(initial, number)
                and expired_season(archive[f'TV/{title}/{number}'], now=now,
                                   days=int(settings.get('HOLDING_DAYS', '7')))
            ]
            deleting = bool(expired) and not plan.restore
            choices = plan.restore or (tuple(sorted(expired)) if deleting else plan.stage)
            if plan.blocked or not choices:
                continue
            restore = bool(plan.restore)
            season = choices[0]
            folders = initial['staged' if restore or deleting else 'active']
            holding = initial['holding_parent']
            if not restore and not deleting:
                root = _open_directory(str(holding.parent))
                try:
                    try:
                        os.mkdir(holding.name, mode=0o755, dir_fd=root)
                    except FileExistsError:
                        pass
                    else:
                        os.fsync(root)
                finally:
                    os.close(root)
            monitor = SonarrSeasonMonitoring(base_url=settings.get('SONARR_URL', ''),
                token=settings.get('SONARR_API_KEY', ''), source_path=initial['sonarr_path'],
                title_folder=title, series_id=initial['series_id'], season=season,
                verify_binding=verify_settings, deadline_tick=deadline)

            def read_plan():
                current = inspect_show(title, read_settings, lambda: session.state)
                for field in ('active_parent', 'holding_parent', 'series_id', 'sonarr_path'):
                    if current[field] != initial[field]:
                        raise RuntimeError('Show binding changed before season move')
                if current['staged' if restore else 'active'].get(season) != folders[season]:
                    raise RuntimeError('Selected season changed before move')
                return current['plan']

            if deleting:
                delete_season(attempt, title=title, season=season, review=initial, now=now,
                    read_review=lambda: inspect_show(title, read_settings, lambda: session.state),
                    monitoring=monitor, read_settings=read_settings)
                deleted.append({'title': title, 'season': season})
                slots -= 1
                continue
            move_season(attempt, title=title, season=season, name=folders[season]['name'],
                        active_parent=str(initial['active_parent']), holding_parent=str(holding),
                        restore=restore, read_plan=read_plan, monitoring=monitor)
        except (OSError, ValueError, RuntimeError):
            session.verify()
            if session.state[KEY]['journal'] is not None:
                raise
            continue
        completed.append({'title': title, 'season': season, 'restored': restore})
        slots -= 1
