# Branch and release workflow

`main` contains the release source. Maintainer development has used
`feature/unraid` and topic branches; historical branches can diverge substantially
from `main`. Start new work from the current released baseline and review it in a
pull request. Preserve persistent state compatibility and keep commits focused.

## Checks

[Python safety checks](../.github/workflows/python-safety.yml) compile Python,
exercise Chromium navigation/settings, check widget examples, and run the test
suite. [Security audit](../.github/workflows/security-audit.yml) audits Python
packages and scans the runtime image. [JSON worker candidate acceptance](../.github/workflows/json-worker.yml)
builds an exact image and tests its packaged entrypoint and disposable recovery
scenarios. Check the run for the exact commit being released.

## Image publication

1. Run candidate acceptance with publication enabled to publish
   `json-candidate-<source-revision>` after successful checks.
2. Record the accepted image digest in the Unraid template and review the release.
3. Merge the checked release into `main`.
4. Dispatch **Docker Image** on `main` with `promote_stable=true` and `publish=false`.
   It reads the pinned template digest, tags that same image as `:stable`, and
   verifies the resulting digest.

A template pin can refer to an accepted image built from an earlier commit whose
runtime source is identical. A later template/documentation commit does not
require rebuilding that image. `:stable` advances through explicit promotion;
publication alone does not update a host container.

Retained host backups and stopped containers are separate from source branches.
Preserve them as needed for recovery. The historical
`json-cutover-verified-2026-11-04` tag preserves an earlier accepted source state.
