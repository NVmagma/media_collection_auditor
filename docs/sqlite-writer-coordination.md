# Writer coordination: implemented application boundary and remaining ownership

Gate 6 remains open. This contract separates enforced cooperating-process
coordination from the external-writer exclusion still needed for production
SQLite moves. No configuration flag can establish that exclusion.

| Writer/path | Current coordination | Remaining limitation |
| --- | --- | --- |
| Scheduled/manual audit worker | `audit_run_lock(STATE_FILE)` holds the adjacent persistent state lock for the full audit | Other applications can ignore this advisory lock |
| JSON state saves | `state_writer_lock(STATE_FILE)` shares that lock; nested saves reuse the held audit context | Correct shared state/lock configuration is required |
| Offline JSON migration | `migration_lock(source)` requires the same adjacent lock | Older/noncooperating instances must still be stopped |
| Manual rescue | Now holds `audit_run_lock(STATE_FILE)` from before library/state reads through move, save, history and Arr notification | JSON rescue still lacks a filesystem/SQLite transaction; this does not solve move recovery |
| Isolated SQLite runner/batches | Separate persistent marked-lab root lock plus revision checks | This lab lock does not coordinate production JSON or external media writers |
| Arr imports/upgrades/renames | No enforced participation | Requires a reviewed ownership/maintenance model |
| Jellyfin sidecar/media writes, download/import tools | No enforced participation | Mount/write access and coordination must be reviewed |
| Host/share clients, manual shells, Docker/mount administrators | Not excluded | Container inventory or a lock cannot prove their absence |

The manual-rescue API keeps its in-process run guard, authentication, CSRF,
path checks, same-filesystem restriction and Dry Run behavior. It additionally
rejects unsupported backend settings before claiming a rescue, and rechecks
those settings after auditor import because dotenv can affect the effective
configuration. Another cooperating process holding the state lock returns 409
before library construction, state loading, a media move or service notification.
Unsafe lock binding or other failures remain errors; they are not contention
successes. Both guards release after success or failure.

The state-file path and Dry Run setting are captured for the rescue. Effective
backend/configuration drift detected at action boundaries blocks further work;
JSON writes always target the captured, locked state path. Lock identity is
checked before the rescue helper, before the media move,
before JSON replacement and before Arr notification, as well as on context
exit. Lock replacement detected at those boundaries blocks further actions.
This is observed-boundary checking, not atomic fencing against an arbitrary
writer that can replace lock files or title entries between checks. Lock files
remain persistent; they are never unlinked as a release mechanism.

All cooperating processes must resolve their state configuration to the same
shared lock inode. A similar pathname, a different state-file alias with a
separate adjacent lock, or distinct container storage is not proof of sharing.
The runtime package must include `sqlite_backend_gate.py`; the recipe-only
Python import tests verify this without a Docker build.

## Failure semantics

A busy lock means no rescue is attempted. A failed move leaves state unchanged.
A JSON-save error after a successful media move still leaves a partial outcome:
bytes remain at the destination, old JSON may remain authoritative, notification
is skipped and the error is surfaced. This pre-existing JSON limitation is not
relabelled as a guarded SQLite transaction. A false Arr acknowledgement after
a successful save remains a reported integration failure, not a rollback.
Neither outcome triggers an automatic retry, source cleanup or deletion.

Tests use real child processes holding each cooperating lock and actual
synthetic directory moves. They check exclusion during load, move and service
notification, effective-backend rejection, lock substitution, state-save and
notification failures, guard release, and preservation of unknown state fields.
The maintained test runner exposes `--writer-coordination-only` for this
focused regression set, retaining its fresh-fixture-path and secret guards.
No external service is called. The user subsequently confirmed 113 tests and
19 subtests passed on each persistent Unraid access path through `a15830b`.

## Next production ownership decision

The application now has one explicit shared-lock protocol for its JSON writers.
Gate 6 still needs an independently checkable way to control *all media
writers*, not only these processes. Review a deployment model that either makes
all relevant writers participate in enforceable coordination or supplies a
verified isolation/maintenance boundary for the affected title entries.

That review must identify writable container mounts and host/share access,
prevent uncontrolled writer restarts during the operation, define who can change
mounts/permissions, and detect loss of the boundary. Capability checks remain
filesystem-independent; no filesystem-name whitelist or operator boolean grants
trust. Process crashes and unknown commits must then be rehearsed against the
accepted model. No service stops, mount-mode changes, image build or production
activation are authorized by this document.


The user confirmed share/host writers exist and accepted an initial maintenance
window requirement, without approving operational changes. The concrete
[maintenance ownership plan](sqlite-maintenance-ownership-plan.md) defines the
remaining enforcement and discovery work. Cooperating locks do not replace it.
