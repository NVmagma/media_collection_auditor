# Gate 10 — release and rollback acceptance

Gates 1–9 are closed for the approved scheduled-run model. Gate 10 is open.
Production remains the existing JSON worker/image. Permanent deletion, season
pruning, cross-filesystem moves and SQLite activation remain disabled. This
record does not authorize a production update or cutover.

## Fixed exit requirements

1. Verify the complete runtime in a candidate image, including JSON/Homarr
   compatibility, actual entrypoint refusal of unapproved SQLite activation and
   the accepted scheduled worker. Test the final source revision in full CI.
2. Accept an operational backup/migration/restore rehearsal on disposable Tower
   storage, including an advanced SQLite revision, pending-operation refusal,
   restart persistence and refusal to restore stale JSON. Preserve evidence and
   original state; no automatic activation or live service controls.
3. Prepare a concrete production cutover and rollback package: immutable image,
   verified paths/configuration, retained backup, stopped cooperating writer and
   explicit recovery rules. No rollback may overwrite newer tracking with stale
   JSON or replay uncertain media/Arr operations.
4. Obtain explicit activation approval after the package is reviewable. Passing
   fixtures or selecting an environment value is not activation approval.

## Candidate runtime packaging

The tracked uppercase `Dockerfile` ships the JSON runtime through an explicit
module list. It cannot package the full accepted SQLite candidate. The repository
also tracks lowercase `dockerfile`; on case-insensitive macOS these paths collide.
This work leaves both recipes untouched and uses the unambiguous
`docker/sqlite-candidate.Dockerfile` instead.

The candidate copies the complete `app` tree once and supplies both package and
legacy flat import paths. It uses Python 3.12 slim through an explicitly supplied
immutable official base digest, labels the exact Git source revision and retains
the unconditional activation gate. No new environment bypass exists.

`scripts/sqlite_candidate_build.py` accepts only `feature/sqlite`, clean runtime
inputs and a pinned official Python base. It builds from `git archive`, not the
potentially colliding/dirty working tree, creates an untagged image, and never
pushes to a registry. The source's requirements are installed; final resolved
package versions still need to be frozen/recorded before a production release.

`scripts/sqlite_candidate_image_lab.py` accepts an exact cached image ID and
matching revision label. It starts only a new constrained container, with no
host mounts, published ports or external network. The actual default entrypoint
serves its private read-only API (401 without token, 200 with the synthetic key),
while a separate actual SQLite entrypoint attempt must refuse activation and
leave fixture JSON bytes unchanged. Accepted coordinator, Arr and TV fixtures
then import application modules from the image, with only committed fixture
scripts copied into container tmpfs. The new container is stopped and removed;
production containers are never inspected for credentials or controlled.

The manual-only `SQLite candidate image acceptance` workflow has contents-read
permissions and no registry publication. It runs the full disposable suite before
building/testing linux/amd64. Local Docker verifies linux/arm64 separately.
Candidate packaging acceptance is pending. Operational restore/cutover acceptance
and explicit production approval remain open.
