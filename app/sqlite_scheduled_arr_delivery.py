"""Configured Arr completion callback for the locked scheduled run body.

Explicit disposable integration only; no production activation or saved request
adoption. The completed batch's exact snapshot is the starting authority.
"""
from contextlib import ExitStack
from copy import deepcopy
import os
import secrets

from app.sqlite_arr_completion import _complete_arr_request_locked
from app.sqlite_scheduled_paths import _open_directory, _canonical

_NAMES = {'Waiting': 'transient', 'Holding': 'holding', 'Keep': 'keep', 'Removal': 'removal'}


def configured_arr_delivery(*, settings, config):
    values = dict(settings)
    used = False

    def complete(*, database, preparation, completed, requests, expected_tracking,
                 verify_binding, remaining, deadline_tick):
        nonlocal used
        if used:
            raise RuntimeError('Scheduled Arr completion cannot be replayed')
        used = True
        if preparation.configuration != config:
            raise RuntimeError('Arr worker configuration changed')
        moves = preparation.plan.moves
        if [row['media_key'] for row in completed] != [move.media_key for move in moves]:
            raise RuntimeError('Only a fully completed bound batch may deliver Arr')
        bindings = {binding.media_key: binding for binding in preparation.bindings}
        identities = dict(preparation.title_identities)
        roots = {(name, stage): (path, identity) for name, stage, path, identity in preparation.root_bindings}
        libraries = {library.name: library for library in config.libraries}
        state, revision = deepcopy(expected_tracking)
        delivered = []
        with ExitStack() as stack:
            handles = {}
            for key, (path, identity) in roots.items():
                fd = _open_directory(path); stack.callback(os.close, fd)
                if (os.fstat(fd).st_dev, os.fstat(fd).st_ino) != identity:
                    raise RuntimeError('Arr root differs from scan')
                handles[key] = fd

            def verify():
                verify_binding(); remaining()
                for key, (path, identity) in roots.items():
                    current = os.stat(path, follow_symlinks=False)
                    if (current.st_dev, current.st_ino) != identity:
                        raise RuntimeError('Arr configured root changed')

            for row, move in zip(completed, moves, strict=True):
                if move.media_key not in requests:
                    continue
                verify()
                library = libraries[move.library]
                binding = bindings[move.media_key]
                if row['library'] != library.name or binding.library != library.name:
                    raise RuntimeError('Arr completed title library mismatch')
                service, prefix = ('radarr', 'RADARR') if library.jellyfin_type == 'Movie' else ('sonarr', 'SONARR')
                request = deepcopy(requests[move.media_key])
                if request['service'] != service:
                    raise RuntimeError('Arr completed title service mismatch')
                source = dict(library.roots)[move.source_stage]
                if move.source_stage != 'Waiting':
                    source = values.get(prefix + '_APP_' + move.source_stage.upper() + '_PATH', '').strip() or source
                outcome = _complete_arr_request_locked(database=database,
                    stage_roots={_NAMES[stage]: path for stage, path in library.roots},
                    expected_parents={_NAMES[stage]: roots[(library.name, stage)][1] for stage, _ in library.roots},
                    expected_title=identities[move.media_key], expected_tracking=(state, revision),
                    operation_id='arr:' + secrets.token_hex(16), media_key=move.media_key,
                    title_folder=binding.folder, details=request,
                    source_path=_canonical(source) + '/' + binding.folder,
                    base_url=values[prefix + '_URL'], token=values[prefix + '_API_KEY'],
                    verify_control=verify, deadline_tick=deadline_tick)
                if outcome['revision'] != revision + 3:
                    raise RuntimeError('Arr completion revision chain changed')
                state['arr_sync_pending'].pop(move.media_key)
                revision = outcome['revision']
                delivered.append({'media_key': move.media_key, 'service': service, 'revision': revision})
            verify()
        return {'arr_completed': tuple(delivered), 'final_revision': revision}
    return complete
