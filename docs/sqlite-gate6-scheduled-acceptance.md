# Gate 6 scheduled-run acceptance

Status: implementation, local acceptance and GitHub test CI passed. Only the
operator's native Tower acceptance result remains required before closure. No
production activation, image update or deletion approval is implied.

The user approved this narrower operating model on 2026-10-24. The governing
[scheduled-run contract](sqlite-scheduled-run-contract.md) replaces the former
requirement for host-wide Docker/share/boot fencing. Gate 6 verifies the scheduled
move core against disposable media; production worker activation belongs to Gates
8–10. Do not restore the historical maintenance-fence prerequisites to this gate.

## Exit evidence

| Criterion | Implementation and acceptance |
| --- | --- |
| Full scan before moves | `sqlite_scheduled_plan` and `sqlite_scheduled_disposable_run`; later-library/pagination failure exposes no plan and dispatches no earlier move |
| Daily schedule and ownership | `sqlite_run_schedule` and `sqlite_scheduled_slot`; explicit zone/DST policy, no catch-up, bounded wake jitter, exclusive durable zone/date claim, one cooperating lock throughout scan and batch, failed claims never replay |
| Fresh per-move protection | `sqlite_scheduled_recheck`, `sqlite_scheduled_jellyfin`, `sqlite_scheduled_transport`; uncached GET-only collection, current tracking before/after refresh, all user/page coverage, default/custom tag mapping, changed decision cancellation, bounded response/request budgets |
| Configured source/destination review | `sqlite_scheduled_paths`; explicit four roots, no-follow component traversal, held directories, overlap/alias/occupied-stage checks, same-mount observations, replacement/cross-mount rejection; read-only and non-authorizing |
| Rename and uncertainty | Disposable executor and revision-chained batch; actual no-replace rename, held witness, exact clock/revision transitions, parent fsync, no cross-device copy/delete, retained intent on post-intent failure or SIGKILL |
| Pending-operation review | `sqlite_scheduled_pending_review`; existing rollback-journal DB only, no media paths followed, no WAL sidecar creation, redacted result, no clearance or replay API |
| Accepted concurrency limits | Post-check tag/source races and open writers are documented. No external-writer exclusion or inode-conditional rename claim is made |

Local validation: 171 focused checks and 14 subtests passed on the development
host. Its 27 Linux-only cases were separately executed successfully in a new
Linux/Python 3.12.15 container. That container also passed 11 real private-loopback
HTTP transport cases (including 14 subtests). The container had no host binds,
network access, added capabilities, service controls or production credentials;
all fixture containers were removed. No site packages were needed by those two
standard-library fixture suites.

The existing Python safety workflow now includes `tests/test_sqlite_scheduled*.py`
and `tests/test_sqlite_run_schedule.py` on `feature/sqlite`, in addition to its
existing regression tests. This is a test-only workflow, not an image publication.
CI run [40102472454](https://github.com/NVmagma/media_collection_auditor/actions/runs/40102472454)
passed for implementation commit `f163d17f6f1092d144731481612196e9da254496`:
143 scheduled tests plus 14 subtests, 671 existing SQLite regression tests and
155 isolated safety tests. These are separate workflow steps, not a statement
that the entire release suite has run. Any later acceptance-document-only commit
retains the same app/scripts/tests/workflow implementation tree. No image was
built or published. Native Tower acceptance is the single remaining Gate 6 check;
a passing result from this package closes the scheduled-model gate without new
host-fence requirements. Subsequent worker/release work stays in later gates.

## Native Tower acceptance

Run from a clean, pulled `feature/sqlite` checkout on Tower:

```bash
cd /mnt/user/sqlite_lab_checkout
git pull --ff-only origin feature/sqlite
bash scripts/sqlite_scheduled_gate6_lab.sh /mnt/media/sql_test
```

The script requires an existing cached immutable Python image (default is the
reviewed Python image digest already used for the earlier Tower labs). It does
not pull, build or install packages. `SQLITE_LAB_IMAGE` may select an exact cached
image ID/digest instead; mutable tags and image-declared volumes are refused.
Only committed checkout Python sources are sent to the fixture. The report
prints the source revision. App/scripts changes must be committed first.

It creates one new 0700 `scheduled-gate6.*` directory beneath the explicitly
selected lab parent and binds only that new directory into one new container.
The container has no network, extra capabilities, Docker socket or production
mounts; synthetic HTTP binds only its private loopback. Fixture writes are limited
to new lab data. The new container is removed on success/failure. The lab marker
and acceptance log remain for review; existing lab contents are not modified.
No NFS/SMB/Docker services, exports, storage permissions, boot configuration or
kernel/module settings are changed.

Expected final line: `status=scheduled_gate6_acceptance_complete`, accompanied by
`fixture_only=true`, `production_activation=disabled`, `production_authorized=false`.
A failure or unsupported capability is not a pass and does not enable a fallback.
Review the retained output before changing the selected path or implementation.
Development-host SSH could reach Tower but non-interactive authentication was
unavailable; no Tower test was executed by the development agent.

## Scope after acceptance

The following remain later-gate work, not prerequisites to this disposable
move-verification gate: production multi-library root routing and a global action
budget; settings/UI and worker/manual-run wiring; production transport credentials
and configured library/path routing; Arr/dashboard/TV integration; safe explicit
operator recovery/restore procedures; final full-suite/release-image verification,
rollback acceptance and explicit SQLite activation approval. Cross-filesystem
copy-and-delete, season pruning and permanent deletion stay disabled/deferred.

Passing Gate 6 must not remove those release blockers or select SQLite as the
live backend. Existing cutover guards remain blocking; they will need a reviewed
scheduled-model assessment during production integration rather than an operator
flag that bypasses verification.
