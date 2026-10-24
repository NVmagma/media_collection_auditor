# Gate 8 scheduled production worker integration

Status: in progress. The first integration boundary is implemented; it does not
select SQLite in the production worker or dispatch media operations. Gates 6–7
remain closed under the approved scheduled model. Host-wide service fences are
not prerequisites for this work.

## Configuration and complete inventory boundary

`configured_scheduled_worker` consumes the existing `build_libraries()` dictionary
shape without importing the production auditor or initializing its clients. It
captures explicit daily time/timezone, movie/TV lifecycle roots, wait/holding
thresholds, favorite policy and one action cap shared across all libraries.
Movie keys remain literal folder names; TV keys retain `TV/`. Identical movie
and series folder names route to different libraries. Arr client objects and
credentials are not retained.

`prepare_scheduled_worker` pins every configured stage root by opening each path
component without following symlinks. Cross-library overlap, root identity aliases,
duplicate title locations and title symlinks block preparation. Non-directory
stage entries also block this initial boundary; they are not interpreted as media.
The bounded inventory covers all four stages and every configured library before
protection collection. All collectors finish before lifecycle decisions. Root and
title identities are checked again before returning any plan. One total deadline
and title limit cover inventory and collection. This detects observed changes;
it does not exclude external writers or grant a later operation permission.

The existing authoritative Jellyfin collector supplies scan-time signals through
`scheduled_inventory_signal_reader`, using a detached configured tag mapping.
Missing/partial coverage produces no candidate for that title. No scan-time
signal may replace the mandatory fresh per-move protection check.

Untracked titles are reported without creating clocks. Conflicting/missing clocks
remain blocked by the existing decision bridge. Episode-driven waiting-clock
resets are explicitly rejected until their integration is implemented; this avoids
silently changing the configured TV policy. Whole-show planning does not invoke
season pruning, delete files, deliver Arr requests or change tracking state.

## Acceptance

Development-host scheduled regressions passed 160 tests and 14 subtests. The 46
Linux-only Gate 6/7 cases require actual Linux execution, not a passing skip count.
The new stdlib worker fixture adds eight disposable filesystem cases, including
movie/TV routing, the global cap, duplicate locations, symlink rejection,
root replacement, later-library failure, incomplete Jellyfin coverage and
untracked-clock preservation. Additional focused tests cover custom tags,
configuration detachment, inventory limits and the total deadline.

Run the committed acceptance package on Tower to verify both filesystem views:

```bash
cd /mnt/user/sqlite_lab_checkout
git pull --ff-only origin feature/sqlite
for lab_parent in /mnt/user/sql_test /mnt/media/sql_test; do
  bash scripts/sqlite_scheduled_worker_lab.sh "$lab_parent" || break
done
```

Each run uses an immutable cached Python image, a new `scheduled-worker.*`
directory and a new fixture container. Only that new directory is bound writable;
there is no network, package installation, image pull, Docker socket mount or
production credential/configuration access. It runs eight worker cases, 19 atomic
Gate 7 cases, 27 Gate 6 cases and 11 HTTP cases. Expected final status:
`scheduled_worker_acceptance_complete`. Production activation remains disabled.
Existing media, state, services, exports, boot settings and kernel controls are
unchanged. This accepts the worker preparation boundary, not all of Gate 8.

## Remaining Gate 8 scope

1. Connect real configured roots/database to the guarded intent, descriptor-bound
   no-overwrite rename and exact atomic reconciliation flow. Preserve Gate 6/7
   behavior without removing disposable markers from their test-only APIs.
2. Integrate discovery clocks and the configured TV new-episode reset policy,
   retaining durable revision checks and the all-library scan barrier.
3. Connect the daily worker/slot ownership and settings path, with one run-wide
   action cap, duplicate-run prevention and no uncertain-operation replay.
4. Verify both production-shaped movie/TV routing and unchanged JSON execution
   through end-to-end disposable acceptance. Keep backend activation blocked
   until the later integration/release gates and explicit approval.

Configured Arr delivery and dashboard authority belong to Gate 9; final image,
backup/rollback and activation approval remain Gate 10 work.
