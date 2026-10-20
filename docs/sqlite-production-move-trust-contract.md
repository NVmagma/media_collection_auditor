# SQLite production move trust contract — blocked draft

This is the gate 6 acceptance contract, not approval to enable SQLite. The
production backend gate still requires JSON. The current executable runner is
restricted to marked disposable fixtures.

## Supported first execution model

The first proposed production model is one Linux mount, held source/destination
parent directories, and atomic no-replace directory rename. A held pre-rename
source descriptor must match the destination after the rename. Clocks and a
bound Arr queue entry can commit with intent clearance only after all required
in-process checks pass. There is no cross-filesystem copy/delete fallback.

The isolated implementation now additionally reads `mnt_id` from each held
parent/source descriptor's `/proc/self/fdinfo` record and captures the current
mount namespace identity. All three directories must have one mount ID and one
device. It rechecks the binding before intent and at execution boundaries.
Unavailable/ambiguous mount information fails closed before intent. A changed
binding after intent preserves the intent and stops further operations.
Linux documents this namespace-local descriptor field in
[proc_pid_fdinfo(5)](https://www.man7.org/linux/man-pages/man5/proc_pid_fdinfo.5.html).
Persisted mount IDs are diagnostic history only: they can be reused and do not
establish identity after restart or across containers.

Non-Linux hosts cannot perform the no-replace rename and remain non-execution
test environments. The mount check applies to Linux descriptor-bound execution;
legacy disposable helpers retain their existing test behavior. Nothing bypasses
the Linux-only syscall guard or authorizes a non-Linux filesystem move.

## Ownership requirements still not established

The runner flock excludes only cooperating processes using that lock inode.
It does not exclude Arr imports/upgrades/renames, manual shell moves, share
writers, other containers, or mount administration. A marker, configuration
boolean, inode match or operator-supplied root string does not prove exclusion.
A same-mount observation does not solve the source-entry substitution window.

Before gate 6 can close, the deployment must have a reviewed way to ensure
exclusive ownership of the relevant title entries during verification and
rename. Either all possible writers participate in enforceable coordination,
or the deployment provides an independently checked isolation/maintenance model.
The review must enumerate those writers and identify how failures are detected.
Do not implement an `exclusive_writers=true` flag that merely suppresses blockers.

## Crash and uncertain-commit policy

- Durable intent precedes any move. Failure to confirm it means no move.
- Loss of the in-process witness means no automatic move-completion claim.
- After restart, any unresolved intent stops the runner; never replay a move.
- A destination folder, matching inode/device, mount ID, or matching remote
  response alone cannot clear a crashed intent.
- Before a final commit, failures leave the original clocks and intent pending.
- An exception after commit requires reopening authoritative SQLite state. If the
  complete clock/Arr queue/intent transaction is present, do not repeat the move;
  if not, leave the move unresolved. Never restore stale JSON over newer state.
- The recovery path must preserve evidence and supply operator diagnostics. An
  operator-approved recovery operation still needs a distinct reviewed contract;
  no generic success flag can authorize clearance.

## Acceptance evidence still needed

1. Verify actual Unraid source/destination mounts and supported filesystem
   semantics without relying solely on share paths or device numbers.
2. Establish and test the complete external-writer ownership mechanism.
3. Run process-level crash/failure tests against that model, including unknown
   commit outcomes, mount/path substitution and source-entry replacement.
4. Review restart diagnostics and the explicit operator recovery procedure.
5. Then assess gate 7 using this accepted verifier before wiring gate 8.

The current mount increment advances item 1's executable checking, not all five
items. It does not complete a production gate, perform live service actions,
change the running container, authorize SQLite activation, or enable deletion.
