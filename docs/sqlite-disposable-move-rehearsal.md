# Disposable-file SQLite recovery rehearsal (isolated executable available)

Status: **design only**. Do not run a filesystem move until the operator
reviews this plan and the dedicated lab mount. This rehearsal is not
production activation or permission to enable reconciliation.

## Existing isolation requirements

Use only the `sqlite-lab` Compose profile and the existing
`scripts.sqlite_lab_preflight` checks. The lab container must have
`network_mode: none`, no privileges, a read-only `/workspace`, and a
single dedicated writable `/lab` bind mount. The pinned Python image,
non-root UID/GID, and host lab directory must be reviewed before any run.
Never bind Jellyfin, Radarr, Sonarr, production appdata, or media libraries.

## Disposable fixture contract

- A new, empty, dedicated `/lab` directory with no symlink ancestors.
- A uniquely named source file with known bytes and an expected SHA-256,
  created inside `/lab` only. Destination must not exist.
- A fresh experimental SQLite snapshot with a durable move intent and
  pre-move evidence before attempting a file operation.
- No cleanup or overwrite on failure; retain fixtures for inspection.
- Read-only inspection must not change either file or SQLite revision.
- All paths must remain inside the reviewed `/lab` mount. Reject symlinks,
  nested mounts, unexpected preexisting fixtures, and unknown file types.

## Crash-window acceptance matrix

| Window | Fixture state | Expected SQLite state | Required behavior |
| --- | --- | --- | --- |
| Before intent | Source only | No pending intent | No move permitted |
| After intent, before move | Source only | `intent_recorded` | Block retry and clearance |
| After disposable move, before applied checkpoint | Destination only | `intent_recorded` | Block retry and clearance |
| After applied checkpoint, before reconciliation | Destination only | `applied_pending_reconciliation` | Block clearance |
| Partial/copy ambiguity | Source and destination | Pending | Block and retain both |
| Missing fixture | Neither | Pending | Block and retain evidence |
| SQLite unavailable or changed | Any | Unverified | Fail closed; do not touch files |

For each row, repeat the read-only inspection after stopping and recreating
the isolated container. Confirm file bytes/hash where applicable, unchanged
SQLite revision, and no external API calls. A destination-only observation
is **not proof** that the expected original file moved.

## Preconditions before executable implementation

1. Review exact host bind mounts, UID/GID, pinned image digest, and preflight.
2. Implement a fixture-only executable with hard-coded, uniquely prefixed
   names and strict `/lab` path guards; never accept arbitrary media paths.
3. Unit-test rejection of symlinks, nested mounts, unexpected files, and
   attempts to overwrite or delete existing data.
4. Run both GitHub Actions workflows successfully.
5. Obtain explicit approval for the isolated disposable-file rehearsal.
   No production media moves or permanent deletion are permitted.

## Rollback and result recording

Do not automatically undo or reconcile an ambiguous operation. Stop the lab,
capture the sanitized status and fixture hashes, and review the state before
manual cleanup of the dedicated disposable directory. JSON remains
authoritative in production; SQLite reconciliation remains disabled.

## Initial read-only fixture guard

`scripts/sqlite_lab_fixture_guard.py` provides an initial non-destructive
check for the exact `/lab` mount and fixed disposable fixture names. It
refuses occupied fixture slots, including dangling symlinks. This is **not**
a move executor or authorization to run a rehearsal. Guard unit tests use
temporary directories and do not access `/lab`.

## Read-only existing fixture inspection

The guard can now inspect local metadata for a previously created source or
destination fixture. It rejects missing files, symlinks, directories, and
multiply linked regular files. A passing observation is explicitly
`observed_unverified`: it cannot prove cross-restart object identity or
clear a pending SQLite operation. No fixture is created or moved by this
inspection, and the test suite uses temporary files only.

## Bounded fixture digest observation

The read-only guard now checks a previously created disposable source or
destination against a caller-provided lowercase SHA-256 digest. It refuses
symlinks, multiply linked files, files over 1 MiB, invalid digests, and
changed or unavailable fixtures. Even a matching digest is reported only as
`observed_unverified` and **never** authorizes reconciliation. This is a
small test-fixture limit, not a production-media hashing policy.

## Advisory mount-boundary inspection

A separate read-only guard inspects supplied mountinfo text and blocks
missing or ambiguous `/lab` mounts, nested mounts, and non-root bind
mount roots. Passing means only `observed_unverified`, never authorization
for any file operation. Mount observations must still be paired with the
existing Compose and host preflight review before a future rehearsal.

The mountinfo boundary check now also rejects malformed record separators,
invalid mount identifiers, noncanonical root or mount paths, and escaped
mount roots. These checks are advisory and do not enable file operations.

## Read-only readiness summary (not a preflight executor)

`assess_disposable_rehearsal_evidence` combines four caller-supplied advisory
observations: mount layout, source checksum, destination vacancy, and fresh
experimental SQLite state. Missing, blocked, or unrecognized observations
produce named blockers. Even a complete set returns `review_required` and
`authorization: not_authorized`. This pure function does not collect or
authenticate observations, inspect production, start containers, create
fixtures, or perform a move. Dedicated lab review and explicit operator
approval remain prerequisites for any future executable rehearsal.

## Read-only destination vacancy observation

`inspect_disposable_destination_slot` now checks only the fixed disposable
destination name with `lstat`. Existing files, directories, and dangling
symlinks are blocked; an absent slot returns `slot_unoccupied_unverified`.
This is a time-of-check observation, **not** an exclusive reservation or
permission to write. The readiness summary can consume it as advisory input.

## Executable disposable lab phases (operator review required)

The experimental `scripts.sqlite_disposable_rehearsal` command now provides
four explicit phases: `prepare`, `move`, `applied`, and `inspect`.
Each invocation is a separate process; stop/recreate the container between
phases to test persistence. The CLI **only accepts /lab** and requires
`--execute-disposable-lab`. The mountinfo guard blocks unsupported bind
mount roots, so an ordinary Docker subdirectory bind may need a reviewed
isolation adjustment before running. Do **not** bypass the guard.

Before starting, create an empty dedicated host directory named with
`sqlite_lab`, review that it is outside all media/appdata mounts, set the
reviewed `SQLITE_LAB_DIR`, non-root `SQLITE_LAB_UID` and
`SQLITE_LAB_GID`, and pinned `SQLITE_LAB_IMAGE` environment variables.
Run `PYTHONPATH=. python -m scripts.sqlite_lab_preflight` on the host.
Check `docker compose -f docker-compose.sqlite-lab.yaml --profile sqlite-lab
config` and confirm **only** the disposable host directory is writable.

For each phase, run an explicitly new container using the same reviewed
Compose configuration:

```sh
docker compose -f docker-compose.sqlite-lab.yaml --profile sqlite-lab run --rm sqlite-lab -m scripts.sqlite_disposable_rehearsal prepare --execute-disposable-lab
docker compose -f docker-compose.sqlite-lab.yaml --profile sqlite-lab run --rm sqlite-lab -m scripts.sqlite_disposable_rehearsal inspect --execute-disposable-lab
docker compose -f docker-compose.sqlite-lab.yaml --profile sqlite-lab run --rm sqlite-lab -m scripts.sqlite_disposable_rehearsal move --execute-disposable-lab
docker compose -f docker-compose.sqlite-lab.yaml --profile sqlite-lab run --rm sqlite-lab -m scripts.sqlite_disposable_rehearsal inspect --execute-disposable-lab
docker compose -f docker-compose.sqlite-lab.yaml --profile sqlite-lab run --rm sqlite-lab -m scripts.sqlite_disposable_rehearsal applied --execute-disposable-lab
```

All reports remain `blocked` and `not_authorized`. The move uses an
exclusive hard-link operation followed by unlink, never destination overwrite.
If interrupted between those steps, **both files remain**, and a retry is
blocked. Do not automatically clean up or retry; preserve fixtures for
inspection. The command never reconciles an intent or touches media roots.
Run only after the workflows pass and host mount configuration is reviewed.

## Unraid shfs readiness note (2026-10-19)

The selected host directory is `/mnt/user/sqlite_lab_test` on Unraid
`fuse.shfs`. Docker Engine 29.8.2 and Compose v2.40.3 were reported.
The Compose entrypoint is now `python`; use `-m` after the service name
rather than a second `python`. **Do not execute the move yet**: a bind of
a subdirectory may report a non-root mountinfo root, which the current
conservative guard intentionally blocks. First capture a read-only mountinfo
observation from the reviewed, isolated Python lab image and confirm its
identity and non-production mount set. Do not relax the root check based on
an unverified root string. FUSE persistence and directory fsync behavior
also require an actual host rehearsal; CI cannot establish Unraid durability.

## Read-only mount probe

Before executing any disposable phase, run the isolated Compose service's
read-only probe (after verifying the host preflight and a reviewed pinned
Python image):

```sh
docker compose -f docker-compose.sqlite-lab.yaml --profile sqlite-lab run --rm sqlite-lab -m scripts.sqlite_lab_mount_probe
```

The probe reads only `/proc/self/mountinfo`. It reports the container's
`/lab` mount root, filesystem type, read-only status, and current guard
verdict; it intentionally omits mount source devices and other host paths.
It never grants permission to move files. A non-root mount root continues to
return `blocked` until reviewed; do not bypass the guard. Running the probe
does not require an empty lab, but the later `prepare` phase does.

## Host-side read-only Compose inspection

From the isolated checkout on the Unraid host, with reviewed
`SQLITE_LAB_DIR`, `SQLITE_LAB_UID`, `SQLITE_LAB_GID`, and pinned
`SQLITE_LAB_IMAGE` environment variables set, run:

```sh
python3 -m scripts.sqlite_lab_host_inspect
```

This checks the host directory using the existing preflight and validates
resolved Compose JSON against exactly two bind mounts, a read-only checkout,
and no networking. It never starts containers and never authorizes writes.
If host Python is unavailable, do not bypass the check or run it inside a
container (that would lose the host filesystem perspective).
