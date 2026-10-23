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


For retained disposable evidence, explicitly select both labs:

```sh
python -m scripts.sqlite_maintenance_review --root /absolute/maintenance-lab \
  --media-root /absolute/media-lab
```

This is optional detached read-only comparison, not a retry command. The reviewer
never derives the media path from stored evidence. A matching identity or absent
pending record never authorizes recovery. SQLite sidecars block comparison
without being recovered or removed. No original media bytes are read or changed.


The focused suite additionally exits a separate controller process abruptly
during collection and at the three native completion fault boundaries. The
parent reviews retained state and must refuse adoption/replay without changing
evidence. These cases bypass Python cleanup using os._exit; they do not emulate
host power loss, server reboot or an external writer fence.

## Selected-writer observations in the independent guest

The disposable wrapper optionally accepts a private `_fixture_boundary_observer`
at its existing held-binding verification points. It must return None or raise;
booleans/receipts are rejected. It supplies an additional deny condition, never
external ownership authority. Existing journal/media locks, scope/identity checks,
protection collection, retention and one-shot behavior remain authoritative.
All external-writer and production permission flags stay false. There is no
production caller or activation path.

On 2026-10-23 the real independent Engine 29.8.2 guest exercised this integration
through `scripts/sqlite_docker_copy_guest_lab.py`, invoked by the writer rehearsal's
`--integrate-copy` option. The synthetic title/state reside beneath the same bind
exposed to the selected synthetic writer. Its observer requires the owned policy
process alive, fresh Engine info identifying the expected authorization plugin,
and a fresh strict stopped/restart-disabled observation of that exact writer ID.
Jellyfin collection uses fixed synthetic data; no production network is accessed.

The healthy case completed the real SQLite/copy/quarantine checkpoint and retained
original bytes without releasing maintenance. The second case killed the policy
at collection. The next observation blocked completion; the original title and
state database were unchanged, the one-shot attempt remained recorded, and the
maintenance phase stayed work_pending with no resume/release authority. No syscall,
identity witness or production guard was mocked for these guest outcomes.

This accepts selected-writer loss handling at the exercised boundary. It is not
full external-writer exclusion, a coherent cross-service transaction, protection
against a change after inspection, a replacement for NFS/boot/administrative
controls, or acceptance of every completion fault point. A no-op callback cannot
confer a permit because this wrapper remains disposable and non-authorizing.

Local validation for this increment: 97 focused checks passed with six existing
platform capability skips on macOS. The real guest independently exercised the
healthy Linux publication/quarantine path and the collection-time policy loss.
Evidence was archived; the independent guest was powered off. No new Tower test
or production service change was needed for these two cases.

## Real policy loss at media-action boundaries

The independent guest subsequently accepted real policy-process SIGKILL at the
first existing binding check observing destination publication, source quarantine,
or committed media checkpoint, as well as collection. No rename, hashing, SQLite
commit or live witness syscall was replaced. Each case retains the original bytes
at their appropriate source/quarantine location and leaves maintenance work_pending.
Publication/quarantine retain pending media evidence; the committed-checkpoint
case explicitly reports absent pending intent as not completion proof. None grants
media-outcome verification, release or production authority after boundary loss.

The updated `--integrate-copy` rehearsal reloads only the same persisted deny
policy between cases. It never restarts the writer or clears an attempt. Same-
controller retries were rejected as already attempted at all four real boundaries;
all retained media/journal file bytes stayed unchanged. A later controller was
separately rejected by session binding for all four retained attempts. The first
later-controller checker incorrectly expected the same-controller error, and the
first nested same-controller setup omitted its media directory; both harness
expectations/setup were corrected without changing application guards. Failed
fixture artifacts were retained.

69 local focused checks passed with six existing macOS capability skips. Real
Linux guest acceptance covers the action syscalls missing from those platform
checks. Original/synthetic copy bytes and uncertainty evidence remain retained.
These checks do not establish continuous exclusion between observations or combine
all production Docker/NFS/host administrative controls into an ownership permit.
