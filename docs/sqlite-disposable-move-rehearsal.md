# Disposable-file SQLite recovery rehearsal (proposal; not yet executable)

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
