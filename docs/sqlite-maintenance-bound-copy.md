# Maintenance-bound disposable copy integration

This integrates existing **disposable** protocols. It does not implement a
production NFS/Docker fence, remove a cutover blocker, or authorize SQLite.

## Contract

`run_maintenance_bound_disposable_copy` requires two separate canonical marked
roots: a media lab with state.db and a Linux boot/network/controller-bound
maintenance journal already at `work_pending` with the expected revision.
Portable unbound journals, unknown phases/revisions and client-writeback holds
cannot start collection. No caller-supplied exclusion boolean is accepted.

The wrapper holds the maintenance controller lock and media runner lock across
collection, copying, publication/quarantine and state reconciliation. Before
collection it commits a one-shot operation binding to the journal: media root
path/device/inode, state database identity and operation identity. That binding
remains on every outcome, including a failed GET before any media intent.
Another invocation cannot replay or adopt it, even if it supplies the same ID.

The initial SQLite write transaction is committed before external work, while
the controller lock stays held. Boundary checks use fresh journal reads, rather
than hiding changes behind a long-lived SQLite snapshot. They recheck boot/net/
controller/root/lock identities, expected phase/revision, the client hold, media
root/database identities and the persisted operation binding. Loss stops further
work. Existing content, protection, deadline, single-link, no-overwrite and
retained-original verification remain mandatory through the existing core runner.

Only a live verified core result can record `outcomes_verified`. The wrapper
never releases maintenance, restores services, clears a writeback hold, delivers
Arr requests, deletes original bytes or grants external-writer exclusion. A
failure after the media transaction commits can leave media reconciled while
the maintenance journal stays `work_pending`: retain evidence and review both
states. Do not retry to repair that uncertainty.

Detached read-only maintenance review reports a retained media attempt without
reading it as a permit or clearing it. A stored binding is diagnostic history,
not a live witness usable by another process or after boot/namespace drift.

## Acceptance check

```sh
bash scripts/sqlite_maintenance_bound_copy_checks.sh /mnt/user/sql_test /mnt/media/sql_test
```

Uses the shared pinned-image disposable launcher, read-only selected source
mounts, new lab directories and noexec temporary dependency storage. It performs
no NFS control, module load, production service change, Docker build or existing
container update. Network access is used only to install Python dependencies;
collectors in tests are fake. Real directory operations affect synthetic labs.

The suite covers holds before collection, failed-attempt replay rejection,
control/media path or database replacement, journal phase/hold/operation drift,
lock exclusion during collection, unbound-journal rejection and native completion
faults at retirement intent, source quarantine and post-commit boundaries.
Linux-only directory-action tests skip on the development Mac. A filesystem
that refuses atomic publication must retain source/intent; those completion
fault cases are explicitly skipped there rather than weakening the syscall or
pretending the crash boundary ran. Native Unraid acceptance is required for the
actual publication/quarantine cases. Other checks still run on both paths.

This is cooperative integration evidence only. An arbitrary external writer can
ignore these locks and replace entries between checks. A real maintenance
adapter, complete external-route/restart coverage and source-entry protection
under that boundary remain required before Gate 6 closes.

Local validation: the maintained maintenance-only suite passes 261 checks with
three actual-Linux directory-action cases explicitly skipped on the development
Mac. Focused integration/hold/review/launcher tests pass 46 checks with the same
three skips. Linux boot/net readers are simulated only in the Mac protocol tests;
the Unraid run uses its actual kernel identities and supported directory syscall.
