# Isolated Unraid SQLite recovery rehearsal (not production deployment)

**Status:** operator confirmed both the isolated JSON marker test and SQLite pending-intent create/verify across separate Unraid containers. Additional interrupted-operation scenarios remain untested. **Branch:** `feature/sqlite`.
**Authority:** production JSON only. **Permanent deletion:** disabled.

## Important image limitation

The current production `Dockerfile` copies selected application files and starts
`python main.py`; it does **not** copy the experimental `app/sqlite_*.py`
modules into the published web image. A successful `feature/sqlite` Docker
workflow is therefore **not** proof that SQLite recovery diagnostics run in
that image. Do not change the production Dockerfile or point an existing
Unraid container at the experimental branch for this rehearsal.

## Preconditions (stop if any fails)

1. Confirm Python safety and Docker workflows succeeded for the exact tested
   commit. Record the commit SHA and image digest; never rely on a mutable tag.
2. Keep the existing auditor container and its `/app/logs` bind mount untouched.
   Verify the actual Unraid host mount mapping and back up
   `auditor_state.json`, `auditor_config.json`, and `auditor_actions.jsonl`
   independently. Do not rename, reset or restore live tracking state.
3. Create a **separate** temporary directory on an Unraid host path, e.g.
   `/mnt/user/appdata/media_collection_auditor_sqlite_lab`, with a dedicated
   `state.json`, `backup.json`, `state.db` and disposable media folders.
   Never mount production media or production appdata into the test container.
4. Use a separate Python 3.12 test container with the reviewed repository
   checkout at the pinned commit and **no access to Jellyfin/Radarr/Sonarr
   credentials or network**. Mount only the lab directory read/write; mount
   code read-only. No host Docker socket, privileged mode, or production volumes.
5. Do not start `main.py`, `collection_auditor.run_once()`, scheduler, web
   server, or any media executor. The rehearsal uses offline diagnostic/test
   functions only.

## Rehearsal sequence

1. Write a minimal disposable JSON fixture including `first_seen`,
   `arr_sync_pending`, and an unknown legacy field. Record a SHA-256 digest
   of its exact bytes. Create separate disposable source/destination folders.
2. Run the reviewed offline migration helper to create an exclusive JSON
   backup and SQLite snapshot. Confirm byte-identical source and backup,
   semantic snapshot parity, and a completed snapshot marker. **No production
   storage selection is changed.**
3. Persist an experimental move intent for the disposable source using
   `SQLiteOperationCoordinator.begin_move_with_evidence()`. Do **not**
   execute a move. Record the SQLite revision and pending phase.
4. Stop and remove the **lab-only** container. Recreate it with the same
   isolated lab mount. Reopen the SQLite state; confirm the pending intent
   persists and a new intent is blocked. Read offline filesystem and recovery
   reports; verify `authorization=not_authorized` and
   `reconciliation=disabled`.
5. Repeat with a **new disposable database** for each simulated outcome:
   source only, both directories present, and destination only. The
   destination-only case may use a manual rename of the **disposable**
   fixture while the lab container is stopped. Neither a diagnostic nor a
   restart may move, delete, or reconcile a file.
6. Rehearse an incomplete SQLite database and a changed JSON source in
   separate lab fixtures. Integrity/preflight must refuse activation; the
   JSON backup must remain intact. Never delete partial output automatically.
7. Compare pre/post JSON SHA-256 digests, file inventories, SQLite revisions,
   pending intent phases, and sanitized diagnostic results. Record results
   without including API credentials or private media paths.

## Stop conditions and acceptance

**Stop immediately** on a missing or unexpected mount, any non-disposable
path in a test command, unexpected filesystem changes, lost tracking state,
successful recovery authorization, cleared intent, stale-session acceptance,
unexpected outbound service call, or integrity/preflight acceptance of a
partial snapshot. Preserve the lab artifacts for inspection; do not
automatically retry or clean them up.

**Pass** requires stable persistent lab state across an actual container
recreation, fail-closed recovery reports, preserved JSON bytes, blocked
reconciliation, and zero unrequested media changes. Record both CI URLs and
the lab run evidence before marking Unraid validation complete.

This checklist does **not** approve SQLite cutover, production image changes,
automatic replay, reconciliation, or permanent filesystem deletion.


## Optional test-only Compose container

The repository includes `docker-compose.sqlite-lab.yaml`. This is an
**offline Python lab**, not the production web image and not an auditor
service. It has no network, no exposed ports, no production media mount,
read-only repository code, and a single explicitly selected disposable lab
mount. It does not start the auditor or execute migrations automatically.

**Before running**, create a fresh empty directory solely for this lab and
confirm its canonical path is not inside production appdata or a media share.
Do not point `SQLITE_LAB_DIR` at `/app/logs`, any production appdata
directory, or a media library. Inspect the rendered Compose configuration
with `docker compose -f docker-compose.sqlite-lab.yaml --profile sqlite-lab config`
before creating a container. Docker bind mounts can create missing host
directories: verify the lab directory already exists and is owned by the
dedicated unprivileged UID/GID you intend to use.

Example, from a checked-out `feature/sqlite` repository:

```sh
export SQLITE_LAB_DIR=/mnt/user/appdata/media_collection_auditor_sqlite_lab
export SQLITE_LAB_UID=1000  # replace with the lab directory owner's UID
export SQLITE_LAB_GID=1000  # replace with the lab directory owner's GID
docker compose -f docker-compose.sqlite-lab.yaml --profile sqlite-lab config
docker compose -f docker-compose.sqlite-lab.yaml --profile sqlite-lab run --rm sqlite-lab
```

The final command only prints an isolation message. Run specific reviewed
offline Python diagnostics with an explicit `--entrypoint python` override,
using only `/lab` fixtures. The Compose file intentionally does not provide
a production deployment path or a command that moves files.

The operator has run the isolated lab on Unraid. A reviewed digest is mandatory through `SQLITE_LAB_IMAGE`; the lab result does not validate the production Docker image.

## Required image pin before starting the lab

Set `SQLITE_LAB_IMAGE` to a reviewed `python:3.12-slim@sha256:<64-hex-digest>` reference before running Compose. The Compose configuration now refuses to start without this variable. Retrieve and verify the real digest from a trusted registry; do not substitute a placeholder or a mutable tag. Independently inspect the resolved Unraid bind mount and ensure the lab directory does not overlap production media or appdata. No production image or container is changed by this configuration.

## Read-only host preflight

Before rendering or starting the lab Compose configuration, set `SQLITE_LAB_DIR`, `SQLITE_LAB_UID`, `SQLITE_LAB_GID`, and `SQLITE_LAB_IMAGE` and run `PYTHONPATH=. python -m scripts.sqlite_lab_preflight` from the checked-out repository. This refuses missing directories, symlinked paths, common production/media directory names, root UID/GID, and unpinned or malformed Python image references. It does not create directories or start Docker. This is a conservative name-based check, **not** proof that a custom Unraid path is isolated: independently verify resolved bind mounts and share paths before any run.

## Missing host paths fail closed

Both Compose bind mounts explicitly set `bind.create_host_path: false`. Docker Compose must reject a missing checkout or lab directory rather than silently creating one. Run `PYTHONPATH=. python -m scripts.sqlite_lab_preflight` **before** rendering/running Compose; the preflight is not automatically invoked by Docker Compose. This does not eliminate mount changes between checking and starting the container. Recheck the resolved Compose configuration and host path immediately before launch.

## First actual-container restart gate: persistent lab mount

This preliminary gate checks only that a disposable file survives a **new
container instance**. It does not yet prove SQLite recovery correctness.

After verifying the pinned image, isolated lab path, host preflight, and
rendered Compose configuration, run these commands from the repository root:

```sh
docker compose -f docker-compose.sqlite-lab.yaml --profile sqlite-lab run --rm \
  --entrypoint python sqlite-lab -m scripts.sqlite_lab_restart_probe create
docker compose -f docker-compose.sqlite-lab.yaml --profile sqlite-lab run --rm \
  --entrypoint python sqlite-lab -m scripts.sqlite_lab_restart_probe verify
```

The first container writes `/lab/sqlite_restart_probe.json` exclusively;
the second container checks its exact JSON content and prints a SHA-256
digest. A pre-existing marker blocks creation, rather than being overwritten.
Never run this with a production bind mount. The script does not delete or
reset the marker. Record the container exit statuses and SHA-256 output.

**Next gate:** independently rehearse SQLite pending-intent persistence and
blocked recovery across container recreation with disposable state. Do not
claim the SQLite restart milestone complete based only on this marker probe.

## Second actual-container gate: SQLite pending move intent

The operator confirmed the earlier disposable JSON marker survived container
recreation. For this **separate SQLite-specific rehearsal**, verify all
preflight and mount requirements again, then run:

```sh
docker compose -f docker-compose.sqlite-lab.yaml --profile sqlite-lab run --rm \\
  --entrypoint python sqlite-lab -m scripts.sqlite_lab_intent_rehearsal create
docker compose -f docker-compose.sqlite-lab.yaml --profile sqlite-lab run --rm \\
  --entrypoint python sqlite-lab -m scripts.sqlite_lab_intent_rehearsal verify
```

The first container creates only `/lab/sqlite_intent_rehearsal.db` and
`/lab/sqlite_intent_rehearsal_source`, records a pre-move intent, and exits.
The second container must print `SQLite restart verified` with a revision
and `status=blocked`. It refuses a second operation and checks that no
new destination appeared. Existing fixtures block `create`; do not delete
or reset artifacts automatically. This test never executes a move and never
clears the pending intent. It does **not** prove recovery for every crash
window, changed mount, or actual move outcome.

## Recorded operator results (2026-10-19)

- Disposable JSON marker persisted across container recreation: **operator reported pass**.
- SQLite pending move intent persisted across container recreation, second operation refused, and `status=blocked`: **operator reported pass**.
- Both GitHub Actions workflows for commit `a2b74b3`: **success**.
- These results are based on the operator's confirmation; raw Unraid command logs and hashes have not been uploaded to the repository.
- **Not yet tested on Unraid:** interrupted checkpoint scenarios, simulated destination-only/both-present recovery, tampered state, and reconciliation safeguards across actual container recreation.

Never use these results to approve SQLite cutover, live media moves, or deletion.
