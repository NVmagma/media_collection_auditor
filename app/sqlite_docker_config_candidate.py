"""Exact Docker-disable review artifacts; no host setting or service control."""
from app.sqlite_nfs_config_candidate import _disabled_candidate
from app.sqlite_disposable_nfs_config_plan import _prepare_disposable_config_plan


def disabled_docker_candidate(content):
    return _disabled_candidate(content, key=b'DOCKER_ENABLED', label='Docker')


def reviewed_docker_restore_candidate(*, original, disabled, current):
    if disabled_docker_candidate(original)!=disabled or not isinstance(current,bytes) or current!=disabled:
        raise RuntimeError('Configuration changed; refuse restoration candidate')
    return original


def prepare_disposable_docker_config_plan(root):
    return _prepare_disposable_config_plan(root, source_name='docker.cfg', plan_name='docker-plan',
        transform=disabled_docker_candidate, restore=reviewed_docker_restore_candidate,
        status='disposable_docker_config_candidates_prepared')
