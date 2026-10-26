# Dispatch controller and recovery integration

Status: implemented and Linux-tested for marked disposable fake-host trees only.
There is no production installation, restoration, controller adoption or writer
permit. JSON remains authoritative; SQLite production activation stays disabled.

## Controller handoff evidence

Before any mount, the controller durably records the exact original identities,
content hashes, root identity and current boot/network/mount namespace. After each
successful read-only guard remount, it writes an exclusive per-route receipt and
fsyncs the receipt and parent directory before proceeding to the next route.
A receipt binds its fixed route, exact mountinfo entry and unique mount identity
to the SHA-256 of the retained request. Existing receipts block a new install.

Complete fence verification now consumes every receipt. Matching guard bytes and
mountinfo alone cannot substitute for a missing or conflicting receipt. Receipt
writes or sync errors stop installation, retaining the request and any installed
mounts. A death between bind and receipt leaves an explicitly unrecorded change;
recovery never infers ownership of that change from its contents.

## Read-only recovery entry point

```sh
python -B -m scripts.sqlite_offline_dispatch_review --root /absolute/disposable/fixture
```

The command opens the existing controller lock without creating or repairing it,
takes an exclusive nonblocking lock, and refuses review while a controller holds
it. It then correlates the strict request, route contents, receipts, scope and
actual current mount identities. Repeated reads check that the evidence remained
stable during review. It does not execute a service or mount command, change a
record, take over an attempt or authorize restoration.

| Observed state | Recovery result |
| --- | --- |
| Live controller/held lock | Review refused |
| Missing controller lock | Failure; lock is not recreated |
| Exact request-bound guard and receipt | Mount observed; hidden original remains unverified |
| Guard installed before receipt | Unreceipted mount blocker |
| Receipt without its exact current mount | Receipt/mount conflict |
| Equivalent bytes on a replacement mount | Conflict; old ownership is not transferred |
| Changed boot/network/mount scope | Scope blocker; no adoption |
| Modified/ambiguous receipt or changed request | Failure; retained evidence is not repaired |

Every successful report remains `review_required`, `restoration_authorized=false`
and `controller_adoption_authorized=false`. These are observations under the
accepted private-store/trusted-administrator model, not authenticated evidence
against privileged record tampering or continuous writer exclusion.

## Mount identity correction

A real Linux replacement test demonstrated that ordinary mountinfo IDs can be
reused immediately after unmount. The new receipt therefore also requires
`STATX_MNT_ID_UNIQUE`; it never falls back to the ordinary ID. The capability is
checked before new installation intent or mounts. Unavailable libc/kernel support
blocks this optional disposable ownership mechanism, without imposing a
filesystem-name restriction on the application. The returned support mask must
confirm the requested field; a fabricated/default number is rejected.

The statx layout and capability mask follow the pinned Linux
[UAPI stat header](https://github.com/torvalds/linux/blob/v6.10/include/uapi/linux/stat.h).
The kernel maintains the unique mount counter separately from ordinary allocated
mount IDs in [namespace.c](https://github.com/torvalds/linux/blob/v6.10/fs/namespace.c).
The existing boot scope still must match; a receipt is never adopted across boots.
Old receipts without a unique identity are rejected, not silently upgraded.

## Actual Linux acceptance

The local, host-mount-free container rehearsal passed complete and partial
installation with real installer SIGKILL. It verified six request-bound receipts
after complete installation, zero receipts plus an unreceipted mount after a
partial bind, refusal while the controller lock was held, retained request bytes,
no automatic restoration, and unchanged underlying originals on namespace exit.
The complete case also unmounted and rebound one inert guard with identical bytes:
verification and recovery review both rejected the new unique mount identity.
49 complete-case and 10 partial-case dispatch attempts remained denied before and
after controller death. This is not an Unraid boot or production service test.

## Still required before restoration

A recorded mount is not enough to safely remove it. Recovery must first verify
the original hidden beneath each guard without exposing an unverified original
service entry. It then needs a separately durable, one-shot recovery intent,
exact owned-change checks at each action, partial-recovery/crash handling and an
explicitly reviewed restoration sequence. Persistent settings, already-running
writers and normal/Safe Mode startup enforcement also remain outside this
fixture implementation. No mount removal or production recovery command is
provided until those requirements are implemented and accepted.
