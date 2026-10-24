# Gate 7 scheduled reconciliation acceptance

Status: **Gate 7 complete for the scheduled model, 2026-10-24.** Implementation,
local acceptance, exact-implementation test CI and native Tower acceptance passed.
Gate 6 stays closed. No production backend selection, image deployment or deletion
is enabled.

## Atomicity boundary

One title's final guarded SQLite transaction removes its source clock, writes
its destination clock, clears its exact applied move intent and, when supplied,
adds the bound Arr retry entry. Unrelated clocks, queue entries and unknown state
fields remain intact. The final transaction advances the applied revision once;
intent and applied checkpoints precede it, so a complete move advances three
revisions. A batch consists of independent per-title transactions, not one
all-or-nothing transaction covering all titles or the filesystem.

Reconciliation now requires the exact applied revision **and** full snapshot
captured by the in-process move session. Previously the final reconciler opened
a fresh session and could adopt an intervening writer's revision. A changed
revision or same-revision state mutation now blocks intent clearance. The final
CAS still rejects a writer racing after that comparison. No caller boolean
bypasses this binding, and a live held directory witness is still mandatory.
Stored fingerprints cannot recreate that witness after restart.

Optional Arr queue requests now pass through the scheduled single-move, batch
and full-slot adapters. They are detached, validated, bound into the durable
intent and included in the exact expected post-move snapshot. Existing target
queue entries are preserved and block a conflicting operation. This persists
retry information only: no Arr API call, automatic delivery or acknowledgement
clearance is performed by Gate 7.

## Exit checks

| Criterion | Acceptance |
| --- | --- |
| Correct lifecycle/queue mapping | Waiting→Holding, Waiting→Keep, Holding→Removal and Holding→Keep, including a TV/Sonarr case, commit the correct clocks and queue fields |
| No partial final state | Actual SQLite triggers abort destination-clock insertion, Arr insertion, intent deletion and revision update; all leave old clocks/queue and applied intent intact |
| Read isolation | An independent connection sees the old applied state before final commit and the entire new state afterward, never an intermediate clock/queue/intent combination |
| Stale-writer protection | Intervening revision, same-revision snapshot mutation and a final-save CAS race cannot clear intent or overwrite the other writer |
| Uncertain acknowledgement | Failure before commit retains old state; failure after actual commit leaves complete new state. Both stop execution, with no automatic retry or guessed rollback |
| Crash behavior | Actual SIGKILL immediately before/after final commit yields complete old/new state respectively; the retained daily slot prevents another attempt |
| Batch behavior | A second-title failure preserves the first atomic result and leaves the second pending; uncertain first acknowledgement stops before the next title |
| Preservation | Unknown state, unrelated Arr entries and bound request contents remain intact; existing target queue data is not overwritten |

The process-kill fixture explicitly opens only its new disposable database for
SQLite rollback-journal recovery, then inspects the recovered state. That is a
storage-engine acceptance step, not an application replay, a production recovery
API or permission to clear a pending operation. Hardware power-loss behavior is
not claimed by process-kill tests.

## Local evidence

The finalized Linux/Python 3.12.15 fixture passed 19 Gate 7 cases, including four
transition subcases. It also passed all 27 Gate 6 regression cases and 11 private
HTTP transport cases. Execution used a new cached-image container with no host
binds, network access, added capabilities, production credentials or site-package
dependencies; the container was removed. Development-host focused regression
checks passed 151 tests and 14 subtests; its 46 Linux-only cases were exercised
separately by the Linux fixture. Existing direct reconciliation and queue tests
were updated to require the new applied-state binding rather than bypass it.

## Test-only CI evidence

[Run 40103818231](https://github.com/NVmagma/media_collection_auditor/actions/runs/40103818231)
passed for implementation commit `7d6823cf211f22490fc0ed9bb984e8105c705ade`:

- Scheduled suite: 164 tests and 18 subtests passed.
- Atomic Gate 7 regressions: 23 tests passed.
- Existing SQLite regressions: 671 tests passed.
- Isolated safety suite: 174 tests passed.

These are separate workflow steps, not a claim that the final release suite ran.
No Docker image was built or published. Later acceptance-document-only commits
retain the same app/scripts/tests/workflow implementation tree. No further Gate 7
implementation item remains; the native result below completes acceptance.

## Native Tower acceptance

The operator supplied passing native acceptance on 2026-10-24:

- Lab: `/mnt/media/sql_test/scheduled-gate7.vPTBGq`.
- Source revision: `0c3336bc570ed83d798c5c6e6e6f22b7e51215ce`, a documentation-only
  descendant with the same implementation tree as the passing CI revision.
- Atomic reconciliation: 19 tests passed in 13.551 seconds.
- Scheduled move regressions: 27 tests passed in 13.517 seconds.
- Private HTTP transport: 11 tests passed in 0.241 seconds.
- Final status: `scheduled_gate7_acceptance_complete`, `fixture_only=true`,
  `production_activation=disabled`, `production_authorized=false`.

The swap-limit warning did not prevent any checks from passing. Only new lab files
and a new fixture container were used; production media, configuration, services,
exports, boot settings and kernel controls were unchanged. Together with passing
implementation CI, this closes Gate 7. No further Gate 7 feature round is required.

The accepted procedure, retained for reproducibility, runs from the pulled
`feature/sqlite` checkout on Tower:

```bash
cd /mnt/user/sqlite_lab_checkout
git pull --ff-only origin feature/sqlite
bash scripts/sqlite_scheduled_gate7_lab.sh /mnt/media/sql_test
```

This follows the accepted Gate 6 lab boundary: immutable cached Python image,
no pulls/builds/package installation, committed Python sources, one new 0700
`scheduled-gate7.*` lab directory and one new unprivileged fixture container.
Only that new directory is bound writable. It runs the 19-case Gate 7 fixture,
27-case Gate 6 regression fixture and private-loopback HTTP fixture. Container
cleanup occurs on success/failure; the new lab marker and log remain. Existing
media, auditor state, exports, services, boot settings, storage permissions and
kernel/module controls remain untouched.

Expected final status: `scheduled_gate7_acceptance_complete`, with
`fixture_only=true`, `production_activation=disabled`, `production_authorized=false`.
Any failing/unsupported scenario prevents that success status. The operator
executed this host acceptance and supplied the passing result recorded above.

## Later gates

Gate 8 production lifecycle integration is next. Production worker/settings/backend wiring, multi-library root routing, configured
credentials and Arr delivery belong to Gates 8–9. Full release/image verification,
operator restore procedures, backup/rollback acceptance and activation approval
remain Gate 10 work. Gate 7 does not enable permanent deletion, season pruning,
cross-filesystem copy-and-delete or automatic recovery of an uncertain move.
