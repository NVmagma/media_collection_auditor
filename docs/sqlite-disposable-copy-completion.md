# Source-retaining copy completion rehearsal

`run_collected_isolated_copy_completion` is a new explicit marked-lab entry point.
It is not called by the production audit or a web route. Existing stage-only and
publish-only entry points retain their behavior and leave pending intents.

The complete fixture flow holds one cooperating-runner lock and:

1. Collects and refreshes complete Jellyfin observations, creates a plan-bound
   verified staging copy and retains its original source clock.
2. Opens live source/copy directory witnesses before atomic no-replace
   publication. It refreshes the same identity/signals again before publication.
3. Keeps both witnesses open, refreshes identity/signals before source movement,
   then persists a separate retirement intent. It renames the original source
   into an exclusive `.sqlite_retained_sources/<operation>` slot using the same
   no-replace primitive. Unsupported capability and occupied slots fail closed.
4. Proves the private original matches its live witness, verifies both content
   manifests and source-entry metadata, checks source absence and unique public
   destination, fsyncs held directories, and rechecks the operation window.
5. In one revision-checked transaction, advances the destination clock, optionally
   enqueues stable Arr work, records a retained-source ledger entry and removes
   the copy intent. No service write is delivered by this flow.

The original bytes are moved into private quarantine, never deleted. Both the
published copy and original remain on disk. This consumes extra storage; there
is no automatic cleanup or approval switch to remove the retained original.
The `sqlite_retained_sources` tracking ledger preserves its private path, title,
digest and completion time as unknown top-level state through snapshot export.
Reports contain only aggregate outcome/authority fields.

Crashes before publication or quarantine verification retain the current intent
and original clocks. Crashes after quarantine leave the original in its private
slot and tracking pending for review. Matching restart manifests are diagnostic
only. A completion attempt cannot resume an already published or uncertain intent:
it must have retained live witnesses from this same invocation. An uncertain
final commit is inspected by reopening SQLite; it is never retried. A committed
transaction contains the new clock, Arr queue/retention record and no intent,
while an uncommitted one retains old tracking plus the durable retirement intent.

The completion rehearsal starts a new bounded observation window after staging
and its content verification finish. Two new complete observations must match
the original title identity and every protection signal before publication. Both
wall and monotonic clocks must remain nondecreasing across the transfer; renewal
cannot conceal a reversal. The configured 1–60 second limit remains unchanged.
This renewal exists only in the same live invocation, under its held lab lock;
persisted pending intents cannot be resumed. The original plan, source clock,
revision checks and conservative lifecycle timestamp remain bound throughout.

Initial pre-intent hashing must still fit its original window. Publication and
completion hashing/checkpoints must fit the renewed window. Deadline checks run
immediately before publication and source-quarantine renames, and before the
completion checkpoint. Slow hashing or checks can still stop with retained data
and a pending intent. Arbitrarily long hashing, asynchronous fresh replanning
and production writer exclusion remain unresolved. A tiny-fixture pass does not
establish large-library production readiness.

This is an isolated workflow for the optional atomic no-replace strategy. It does
not implement a safe publication alternative on unsupported filesystems, source
permanent deletion, production orchestration or restart-clearance authority.
Gate states remain unchanged. User filesystem choices are not a whitelist:
unsupported capabilities produce blocked outcomes rather than an unsafe fallback.

Native Linux tests exercise actual publication, source quarantine, full-show
season preservation, fresh-protection changes, destination races and pre/post
commit uncertainty. General capability tests run on both paths and accept only
successful source-retaining completion or explicit kernel unsupported outcomes.
The maintained runner includes those general cases by default;
`--publication-supported` additionally requires the actual syscall/crash cases.
