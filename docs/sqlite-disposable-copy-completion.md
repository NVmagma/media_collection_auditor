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

The live completion rehearsal performs expensive full content hashing before
fresh protection collection at four boundaries: before the copy intent, before
publication, before source quarantine, and before lifecycle reconciliation.
Each boundary requires two complete observations matching the original identity
and every protection signal. After those scans, a no-follow whole-tree metadata
walk must exactly match the file/directory identities, sizes and nanosecond
mtime/ctime observed while hashing. Hashes are still computed and compared;
metadata is an additional race check, never a substitute for content digests or
proof that a persisted operation completed.

Only this live invocation can start each bounded 1–60 second collection window.
Both wall and monotonic clocks must remain nondecreasing across hashing and
copying. Collection, metadata walks and revision checks must fit the fresh
window, with the deadline checked immediately before the following action.
Slow collection/metadata traversal or a checkpoint delay stops execution. Metadata is rechecked after the publication/retirement
intent checkpoint and before either rename; retained-source path binding is
also rechecked after final collection. The original plan and conservative
lifecycle timestamp stay bound throughout. A successful completion performs
nine complete scans: initial planning plus two for each of the four boundaries.

If protection, content, metadata, path binding or SQLite revision changes after
publication/quarantine, the intent remains pending and original bytes remain at
the original or retained path. There is no rollback-by-copy, source deletion,
automatic retry or restart clearance. Snapshot metadata cannot grant authority
to resume. External writers are not excluded; privileged writers or filesystems
that do not expose changes reliably remain outside this prototype's proof. This
is not a reviewed production verifier, asynchronous worker or capability
fallback for filesystems without atomic no-replace publication.

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


## Holding-source transitions

The same live completion path now supports Holding-to-Keep rescue and
Holding-to-Removal, in addition to Waiting-to-Holding/Keep. One shared mapping
binds source and destination stage names to tracking clock sections. Source
paths, hashing descriptors, plan bindings, inspection, quarantine and final CAS
all use that source stage; Holding uses `queued`, never `first_seen`. The final
checkpoint removes only the bound source clock and writes only the planned
destination clock. The retained-source ledger also preserves the original
source stage and timestamp for review, without granting restore authority.

The existing production decision function controls these candidates. Protected,
keep-tagged or favorite Holding titles rescue to Keep (subject to the existing
favorites setting); expired unprotected titles may move to Removal. A fresh
protection/identity change aborts the old plan rather than silently switching
its destination. Recent/conflicting clocks fail closed. Removal here is a
lifecycle directory, not permanent deletion: the public copy and quarantined
original both remain. All TV seasons are copied intact. Keep/Removal sources,
season pruning and deletion remain unsupported. Existing stage-only helpers
still require Waiting sources; no production audit caller is added.

Unplanned legacy copy intents continue to bind only to the Waiting source.
Plan-bound intents must specify one of the four explicit non-deleting
transitions. Read-only inspection reports the proposed source stage and retains
all previous pending/recovery restrictions. Matching content never authorizes
restart completion.
