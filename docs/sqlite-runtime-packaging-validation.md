# Runtime packaging verification without an image build

The production Dockerfile copies individual Python modules into `/app`.
Dashboard snapshot validation introduced three required runtime files:
`dashboard_tracking_snapshot.py`, `sqlite_json.py` and `sqlite_state.py`.
The recipe now explicitly copies them and smoke-imports the web/snapshot modules
with a build-only session secret. This inline secret does not set a runtime ENV
value or replace deployed session-key handling. No backend is activated.

`test_docker_runtime_context.py` assembles only the Python files listed in those
COPY instructions and starts fresh processes outside the repository. It checks
actual dashboard JSON reads and damaged-state errors. A negative control removes
a dependency to prove repository imports cannot hide a missing runtime file.
This test performs no Docker build, image pull, service request or publication.
It does not replace final built-image verification.

Git contains both `Dockerfile` and legacy `dockerfile`. On case-insensitive
checkouts tests use the exact uppercase indexed recipe when git is available;
on Linux in the pinned Python lab (without git), they read `Dockerfile` directly.
The legacy lowercase recipe is unchanged by this increment.

The consolidated runner now includes packaging smoke checks. `--full-suite`
explicitly runs all tests instead of the targeted integration set. It still
requires a never-before-used absolute basetemp and never retries/repairs a lab.
Full move regressions require Linux with atomic no-replace rename support.
Unsupported access paths must fail closed rather than skipping those checks or
using overwriting rename. Native Btrfs is the verified test path on this host;
this is a test capability requirement, not a public-release filesystem mandate.

Local full-suite evidence: 1,404 passed, 18 failed at the existing Linux-only
rename guard, 30 skipped and 22 subtests passed on macOS. The 18 are not recorded
as passes or silently skipped. A full Unraid/Linux run is required to execute
them. New packaging tests pass independently. Final CI/image verification and
activation approval remain separate outstanding release gates.

`--publication-supported` adds the actual Linux copy-publication crash/race
cases to the targeted set. Use it only on a disposable access path already
verified to support atomic no-replace rename. The default targeted set still
performs an actual capability attempt: success must preserve source/tracking;
explicit unsupported capability must preserve staging/prepared intent. Other
errors fail the test. Full-suite mode includes all publication cases and is
therefore also a capability-requiring run. No flag changes application runtime
behavior, syscall safeguards or production authority.
