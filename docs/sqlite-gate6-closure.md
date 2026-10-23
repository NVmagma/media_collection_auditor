# Gate 6 closure work

Gate 6 remains open. Accepted disposable tests are evidence for individual
requirements; they are not a production ownership permit. JSON authority,
disabled SQLite activation and deletion safeguards remain unchanged.

## Accepted components

- Held directory/mount binding, no-overwrite publication, source retention and
  atomic disposable lifecycle checkpoints have Unraid acceptance.
- Real Jellyfin 12.2.0 reads protections with read-only media, including after
  fixture restart. A RO parent does not cover a RW nested mount.
- Real Mac NFSv3 delayed-write/fsync recovery passed without Tower module loads.
  Paused bytes remained unchanged; queued writes arrived after explicit recovery.
- Disposable Docker failure restart, persistent restart=no and controller-death
  behavior passed. Explicit starts/recreation and daemon/host boot remain outside
  that result.

## Three closure requirements

| Requirement | Work remaining before acceptance |
| --- | --- |
| Enforced ownership and continuity | A real maintenance adapter must cover every relevant container/host/share writer, their storage aliases and pending writes, and administrative restart/recreation/boot paths. It must remain fenced across controller death; no receipt or operator boolean substitutes for enforcement. Mac NFSv3 evidence does not cover NFSv4/Linux LOCALIO. |
| Safe source-entry action under ownership | Bind verified source/destination objects to the accepted ownership boundary. Existing renameat2 no-replace protects the destination but is not inode-conditional source rename. Pre/post checks alone do not eliminate source substitution. Retain originals and pending intents on uncertainty. |
| Integrated crash/recovery acceptance | Rehearse the accepted adapter and verifier together, including boundary loss, queued client writes, source substitution and unknown commit outcomes. Recovery must retain evidence and never automatically reopen writers or clear intents from a matching path/hash alone. |

These are implementation and acceptance requirements, not three more smoke-test
runs. Repeating the accepted NFSv3/Jellyfin tests cannot close them. A future host
adapter will need a concrete reviewed change package before any production
service/startup modification; none is installed by the present work.

## Hard-link ownership gap

A file can have another hard-link name in a download directory or outside a
reviewed media tree. A media-mount write policy cannot establish exclusion of
that other name. Live verified copy-completion checks now reject regular files
whose link count is not exactly one, both before/after opening and at the current
entry binding. The check applies recursively to source and staged/published
copies wherever hash evidence is refreshed/verified. It never removes an alias
or rewrites production data.

Copy-only source-retaining diagnostics still copy those bytes independently and
report no promotion authority. The existing JSON production path is unaffected.
The completion runner blocks pre-existing aliases before durable intent; aliases
introduced later retain pending intent, clocks and original bytes without
publication, quarantine or Arr queue changes at the tested boundaries.

This is a conservative capability/ownership condition, not a filesystem-name
restriction. `nlink=1` is not an ownership permit: bind aliases, existing writable
handles, alternate network routes and races after checks remain separate. There
is no ignore-hardlinks switch. A future backend accepting shared inodes needs an
independently reviewed alias/exclusion model, not a weaker digest comparison.

## Focused Unraid check

```sh
bash scripts/sqlite_copy_ownership_checks.sh /mnt/user/sql_test /mnt/media/sql_test
```

Uses only the cached pinned Python image and new lab subdirectories. Sources
are read-only; only app/tests/requirements are mounted, excluding checkout .env,
production state/media and Docker sockets. Dependency installation uses network
access inside the temporary container; tests use fake collectors. There is no
image build, NFS control, module operation or existing-container update. Lab
artifacts are retained. The user accepted 43 checks on each path with the
corrected launcher through `b484fd9`.

Local verification: 45 focused checks pass, including real hard links and the
inert launcher's source/mount restrictions. The broader maintained run passed
892 checks and 19 subtests but its existing loopback HTTP smoke test hit sandbox
EPERM on socket bind. That five-check HTTP module passed separately outside the
bind restriction; no application assertion or safety guard was changed for it.

### Focused launcher startup correction

The first Tower run stopped before pytest: executing the generated
`/tmp/testenv/bin/pip` script returned permission denied. This supplied no
hard-link test result. Installation now uses the venv interpreter's `-m pip`
entry point, matching the existing `python -m pytest` pattern. The interpreter
symlink resolves to the base runtime outside the temporary mount. `/tmp` is
explicitly noexec/nosuid/nodev; no executable-mount permission is added.

A regression creates a real venv, removes the pip launcher's executable bits,
and verifies module invocation still works. Inert Docker tests also require
noexec and interpreter/module invocation. Actual Tower acceptance requires a
fresh launcher run; failed lab artifacts remain retained.


## Durable uncertain-client hold

The marked disposable maintenance journal now has a deny-only writeback hold.
It records the fixed uncertain-client outcome transactionally under the existing
controller lock and scope checks. It does not advance the lifecycle event revision
or claim that fencing succeeded. Every subsequent transition checks the hold,
so even a caller with the previous matching revision cannot advance/release.
The synthetic release receipt is not created, and old/new cooperative writer
descriptors cannot write after the hold. An unknown/empty hold schema also blocks.

Real child-process exit after commit preserves the hold. Detached read-only
review reports `client_writeback_outcome_uncertain`, without changing source
bytes or granting resume/clearance. There is no clear/delete/force/replay API.
A failed record must abort any proposed external step; a future adapter must
persist the appropriate request/uncertainty state before risking an external
operation, not rely on successfully logging a failure afterwards.

This is fixture journal enforcement, not an external NFS/Docker fence. It is not
wired to production services or represented as production writer exclusion.
Existing journals without a hold keep their synthetic behavior and grant no new
production authority. A released fixture cannot retrospectively record an active
hold; production release still requires an independently accepted client-state
and ownership model. New hold acceptance on Unraid is pending.

Run the focused new regression set using only disposable directories:

```sh
bash scripts/sqlite_maintenance_writeback_checks.sh /mnt/user/sql_test /mnt/media/sql_test
```

The fixed copy-ownership and maintenance-writeback wrappers share the isolated
boundary-check launcher. It mounts app/tests/scripts/requirements read-only,
uses a noexec temporary mount and `python -m pip`, and accepts no arbitrary suite
or command. The scripts mount allows the detached review CLI tests; checkout
.env, state, production media and Docker sockets are not mounted. No NFS controls,
service changes, kernel operations or image builds are involved.

Local validation for the hold increment: 72 focused checks pass and the maintained
maintenance-only suite passes 250 checks. Actual two-path Unraid acceptance is
pending; these results do not claim a real external-writer fence.
