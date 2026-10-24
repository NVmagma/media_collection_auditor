"""Guarded clock checkpoint and fresh plan rebuild in marked disposable labs.

No production backend selection, move dispatch, slot replay or external service
writes. The cooperating runner lock spans collection, one optional checkpoint
and complete recollection. It does not exclude other media writers.
"""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import math
from pathlib import Path
from time import monotonic

from app.sqlite_audit_session import RevisionedAuditSession
from app.sqlite_isolated_lifecycle_runner import isolated_runner_lock
from app.sqlite_scheduled_worker import ScheduledWorkerConfig, prepare_scheduled_worker
from app.state_store import GuardedSQLiteStateStore


@dataclass(frozen=True)
class CheckpointedWorkerPreparation:
    preparation: object
    checkpointed: bool
    initial_revision: int
    final_revision: int
    fixture_only: bool = True
    production_authorized: bool = False
    production_activation: str = 'disabled'


def prepare_checkpointed_disposable_worker(*, root, config, fetch_signals,
        clock=datetime.now, timer=monotonic, maximum_titles=100000,
        maximum_scan_seconds=3600):
    """Produce a current advisory plan after at most one clock checkpoint.

    Proposals are generated inside this call, never accepted from a saved report.
    Any checkpoint exception propagates without retry or dispatch, including an
    exception after the actual commit. A changed second observation stops rather
    than repeatedly updating clocks. Production roots are not accepted here.
    """
    root = _validate_clock_preparation(root=root, config=config, fetch_signals=fetch_signals,
        clock=clock, timer=timer, maximum_scan_seconds=maximum_scan_seconds)
    with isolated_runner_lock(root) as verify_binding:
        return _prepare_checkpointed_worker_locked(root=root, config=config, fetch_signals=fetch_signals,
            clock=clock, timer=timer, maximum_titles=maximum_titles,
            maximum_scan_seconds=maximum_scan_seconds, verify_binding=verify_binding)


def _validate_clock_preparation(*, root, config, fetch_signals, clock, timer, maximum_scan_seconds):
    root = Path(root)
    if (not isinstance(config, ScheduledWorkerConfig) or not callable(fetch_signals)
            or not callable(clock) or not callable(timer)
            or type(maximum_scan_seconds) not in (int, float)
            or not math.isfinite(maximum_scan_seconds) or maximum_scan_seconds <= 0):
        raise ValueError('Bounded disposable scheduled worker configuration required')
    for library in config.libraries:
        for _, path in library.roots:
            if root not in Path(path).parents:
                raise ValueError('Every configured stage must be inside the marked lab')
    return root


def _prepare_checkpointed_worker_locked(*, root, config, fetch_signals, clock, timer,
        maximum_titles, maximum_scan_seconds, verify_binding):
    """Internal composition while the daily claim retains the runner lock."""
    started = timer()
    def remaining():
        elapsed = timer() - started
        if not math.isfinite(elapsed) or not 0 <= elapsed < maximum_scan_seconds:
            raise RuntimeError('Clock preparation deadline exceeded')
        return maximum_scan_seconds - elapsed
    session = RevisionedAuditSession(GuardedSQLiteStateStore(root / 'state.db'))
    source, initial_revision = session.read_verified_snapshot()
    def prepare(snapshot, revision):
        verify_binding()
        result = prepare_scheduled_worker(config=config, snapshot=snapshot,
            revision=revision, fetch_signals=fetch_signals, now=clock(),
            maximum_titles=maximum_titles, maximum_scan_seconds=remaining(),
            timer=timer, discover_clocks=True)
        verify_binding()
        remaining()
        # Covers an independent writer during any collector/content read.
        current, current_revision = session.read_verified_snapshot()
        if current != snapshot or current_revision != revision:
            raise RuntimeError('Clock preparation source changed')
        return result
    prepared = prepare(source, initial_revision)
    proposal = prepared.clock_proposal
    checkpointed = bool(proposal.changes)
    if checkpointed:
        if (proposal.source_revision != initial_revision
                or proposal.source_snapshot != source):
            raise RuntimeError('Clock proposal source binding changed')
        verify_binding()
        session.read_verified_snapshot()
        remaining()
        session.state = deepcopy(proposal.proposed_snapshot)
        session.checkpoint()  # One CAS; any uncertainty stops this call.
        verify_binding()
        after, revision = session.read_verified_snapshot()
        if after != proposal.proposed_snapshot or revision != initial_revision + 1:
            raise RuntimeError('Clock checkpoint result mismatch')
        # Do not lift the old plan's revision or reuse cached protections.
        prepared = prepare(after, revision)
        if prepared.clock_proposal.changes:
            raise RuntimeError('Discovery changed after checkpoint; no dispatch')
    else:
        revision = initial_revision
    verify_binding()
    session.read_verified_snapshot()
    remaining()
    return CheckpointedWorkerPreparation(prepared, checkpointed, initial_revision, revision)
