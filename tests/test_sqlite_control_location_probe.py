import os
from pathlib import Path
import subprocess

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/sqlite_control_location_probe.sh'


def run_probe(tmp_path, *arguments, docker_fails=False):
    tools = tmp_path / 'tools'
    tools.mkdir()
    bodies = {
        'timeout': 'shift\nexec "$@"',
        'stat': 'echo directory_identity=device:1,inode:2,mode:700,uid:0,gid:0',
        'findmnt': 'echo /mnt/media btrfs',
        'exportfs': 'printf \'/mnt/user/appdata client(secret_options)\\n  client(secret_options)\\n\'',
        'docker': ('exit 1' if docker_fails else '''case "$1" in
ps) printf '%064d\\n' 1 ;;
inspect) printf '%s\\n' '/fixture' '  bind_source="/mnt/media" writable=false' ;;
*) exit 1 ;;
esac'''),
    }
    for name, body in bodies.items():
        path = tools / name
        path.write_text('#!/bin/sh\n' + body + '\n')
        path.chmod(0o700)
    return subprocess.run(['/bin/bash', str(SCRIPT), *map(str, arguments)],
        text=True, capture_output=True, env={**os.environ, 'PATH': str(tools) + os.pathsep + os.defpath})


def test_collects_only_selected_metadata_and_never_authorizes(tmp_path):
    candidate = tmp_path / 'candidate'; candidate.mkdir()
    result = run_probe(tmp_path, candidate)
    assert result.returncode == 0, result.stderr
    assert 'candidate_path=' in result.stdout
    assert '/mnt/user/appdata' in result.stdout
    assert 'secret_options' not in result.stdout
    assert 'bind_source="/mnt/media" writable=false' in result.stdout
    assert 'private_location_verified=false' in result.stdout
    assert 'production_authorized=false' in result.stdout
    assert list(candidate.iterdir()) == []


def test_unavailable_docker_stays_explicit(tmp_path):
    candidate = tmp_path / 'candidate'; candidate.mkdir()
    result = run_probe(tmp_path, candidate, docker_fails=True)
    assert result.returncode == 0
    assert 'container_enumeration=unavailable' in result.stdout
    assert 'observation_commands_completed=false' in result.stdout


def test_symlink_alias_is_refused_before_inventory(tmp_path):
    candidate = tmp_path / 'candidate'; candidate.mkdir()
    alias = tmp_path / 'alias'; alias.symlink_to(candidate)
    result = run_probe(tmp_path, alias)
    assert result.returncode == 2
    assert 'container_bind_sources_begin' not in result.stdout


def test_missing_candidate_is_not_created(tmp_path):
    candidate = tmp_path / 'missing'
    result = run_probe(tmp_path, candidate)
    assert result.returncode == 2
    assert not candidate.exists()
    assert 'read_only=true' not in result.stdout


def test_ancestor_only_observes_every_parent_without_deployment_inventory(tmp_path):
    candidate = tmp_path / 'parent' / 'child'
    candidate.mkdir(parents=True)
    result = run_probe(tmp_path, '--ancestors-only', candidate)
    assert result.returncode == 0, result.stderr
    for path in [candidate, *candidate.parents]:
        assert f'ancestor_path={path}\n' in result.stdout
    assert 'container_bind_sources_begin' not in result.stdout
    assert 'nfs_export_roots_begin' not in result.stdout
    assert 'potential_unraid_share_paths_begin' not in result.stdout
    assert 'private_location_verified=false' in result.stdout
    assert list(candidate.iterdir()) == []
