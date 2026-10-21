# Production acceptance plan after the full regression baseline

The full native Unraid suite passed 1,452 tests and 22 subtests through
`ac5d4a7`. The copy root/source-parent follow-up through `4421fce` passed 77
focused tests on both shfs and native Btrfs. These establish regression evidence,
not completed production orchestration. Production authority remains JSON.

The critical path now consists of actual implementation and operational evidence:

1. **Complete a portable move protocol.** Copy staging preserves the
   source and pending intent. Optional atomic no-replace publication now exists
   only in marked labs and retains the source; publication without that kernel
   capability and source retirement remain unimplemented. Define exclusive publication, duplicate handling, failure ordering
   and restart state before coding those phases. Never substitute ordinary
   overwriting rename for a missing no-replace capability. Permanent deletion
   remains separately disabled. Filesystem labels or one successful lab run are
   not a capability/ownership contract.
2. **Establish writer control at the action boundary.** Current locks exclude
   only cooperating app processes. Arr, Jellyfin, shares and host writers may
   still alter media. A supported deployment needs enforceable coordination or
   a reviewed isolation window for affected entries. An `exclusive=true` flag
   is not evidence. Do not pause containers, change mounts, or alter production
   permissions merely to make a rehearsal pass.
3. **Finish reviewed recovery.** Lost live witnesses and ambiguous remote/media
   outcomes remain pending. Define the independent observations and recovery
   decision for each durable phase. No generic approve/clear-success switch,
   automatic replay, or restoration of stale original JSON is acceptable.
4. **Wire production lifecycle paths.** Waiting, Holding, Removal, Keep/season
   handling and Arr retry must use the accepted state/operation boundaries.
   Preserve operation caps, clocks, protections and pending-intent precedence.
   The current real audit path still rejects SQLite before side effects.
5. **Rehearse the completed workflow and release.** Test failure/restart windows
   on each supported strategy. Review a stopped-writer cutover and advanced-state
   rollback procedure. Only after implementation acceptance, verify the actual
   final CI/image and obtain explicit production activation approval. Deletion
   approval remains a separate decision.

Arr readback and dashboard parity now have isolated implementation and server
fixture evidence. Live remote completion/identity mapping, production dashboard
SQLite authority and TV-season execution still require integration acceptance.
Do not relabel synthetic GET tests or whole-show copy tests as those outcomes.

## Cutover assessment behavior

The read-only cutover guard now always reports the currently unimplemented
production components in addition to the approval blocker. Its two integration
inputs are caller claims, accepted only as literal booleans; they cannot remove
implementation blockers. Any pending-operation key blocks, even if its value is
empty or malformed. `activation_supported` remains false. No override switches
exist, and the report performs no migration, state changes or media actions.

No amount of fixture testing alone removes these implementation facts. Update
this plan and the guard only when the relevant implementation and acceptance
evidence exist. Until then, asking for activation approval would be premature.
