# Real Jellyfin read-only-media compatibility fixture

This Gate 6 experiment tests an actual cached official Jellyfin image against
new synthetic media and configuration, not the running production server.
It does not enforce production ownership or close the external-writer gate.
Active NFS-client/kernel tests remain deferred.

Run on Tower from a fast-forwarded `feature/sqlite` checkout:

```sh
bash scripts/sqlite_jellyfin_readonly_lab.sh /mnt/user/sql_test
```

The existing absolute lab parent can be on any supported backing filesystem;
there is no filesystem-name whitelist. A new `jellyfin-ro.XXXXXX` directory is
created exclusively and retained after success or failure. It contains only
synthetic media, fixture credentials and the new server's state/logs. Do not
paste the credentials or unredacted server configuration/logs.

## Isolation and exact scope

- Read only the installed `Jellyfin` container's image reference and immutable
  image ID. Never stop, restart, exec into, copy configuration from or contact
  that container. The adapter currently requires the official `jellyfin/jellyfin`
  image layout; unsupported cached layouts fail without pulling another image.
- Reuse the previously accepted cached Python digest. Every run uses
  `--pull=never`; no Docker build, image download or package install occurs.
- Generate one second of synthetic video using the cached Jellyfin image's
  software ffmpeg. Only the newly created media directory is writable there.
- Create one new label-bound Jellyfin server with network `none`, no published
  ports, read-only root/media, dropped capabilities, no privileged/devices/socket
  access, capped memory/CPU/PIDs and a five-minute internal lifetime per start.
  Its configuration and cache use fresh writable lab binds; temp remains a
  small tmpfs. No production cache/configuration is mounted.
- A fixed-loopback Python client shares only that new server's network namespace.
  It reads the app collector/client source and synthetic media read-only, and
  writes only its new control directory. It accepts no target URL or real API key.
  Client/ffmpeg processes have internal deadlines in addition to CLI timeouts.
- Configure a new fixture-only admin and library during that server's fresh
  startup wizard. Fixture setup POSTs are not retried. Set one fixture favorite;
  import keep-forever from the synthetic NFO. These writes affect only new
  Jellyfin state and are separate from production collector GET behavior.
- Require one explicit write probe to fail with EROFS, unchanged media digests,
  stable new server identity and fresh successful protection collection using
  the existing experimental collector. A permissions error is not EROFS proof.
- Verify the server's actual Docker network/root/media policy, restart only its
  new ID after checking its unique label, then repeat protection and byte checks.
- Cleanup removes only that label-verified server ID. Lost identity prevents
  further lifecycle commands. The internal lifetime bounds an abandoned server
  if the host launcher is killed. Nothing restores or modifies production.

## Protocol/source review

Setup follows Jellyfin's pinned v10.11.0
[startup controller](https://github.com/jellyfin/jellyfin/blob/v10.11.0/Jellyfin.Api/Controllers/StartupController.cs),
[library setup controller](https://github.com/jellyfin/jellyfin/blob/v10.11.0/Jellyfin.Api/Controllers/LibraryStructureController.cs)
and [favorite endpoint](https://github.com/jellyfin/jellyfin/blob/v10.11.0/Jellyfin.Api/Controllers/UserLibraryController.cs).
The installed image may differ; fixture execution is required and unexpected
responses block rather than falling back to production or repeating writes.

Local tests cover fresh-server refusal, setup ordering, real collector response
validation, missing protections, media mutation, EROFS versus permissions/writable
outcomes, redirect refusal, exclusive fixture credentials, private output and
new-ID/label-only lifecycle actions. Docker calls are inert stubs locally; no
actual Jellyfin service is claimed tested on this macOS host.

## Acceptance limits

A successful report establishes this fixture image's local media-read/protection
compatibility with its declared Docker read-only policy, including a fixture
restart. It does not establish production Jellyfin remount behavior, all live
nested bind routes, administrator/daemon restart inhibition, NFS client caches,
privileged bypass exclusion, atomic source-entry fencing or a production permit.
Every output keeps `writer_exclusion_verified=false` and activation disabled.
The test neither moves tracked media nor changes SQLite production authority.

Local validation: 842 maintained tests and 19 subtests passed on macOS/Python
3.12 before the final cleanup-policy refinement; the final 16 focused protocol
and launcher tests also pass, including refusal to report completion after
cleanup failure. Shell syntax and diff whitespace checks pass. Actual cached
Jellyfin startup/scanning/restart on Tower is still required; no success is
inferred from the inert local transport/CLI doubles.

Tower's first attempt retained `jellyfin-ro.BMfwUE` and timed out waiting for
startup. This is failed fixture acceptance, not proof of a Docker swap-limit,
filesystem, permission or networking cause. The launcher now retains its new
container's bounded private stdout log plus selected running/exit/OOM state
before cleanup on failure. Original fixture application logs may also remain
under its fresh config/log directory. Do not rerun or change production controls
until the available fixture diagnostics have been reviewed. Six launcher-policy
tests pass for the diagnostic refinement, including label-loss refusal.


### Startup capacity failure diagnosed

The retained Tower fixture log identifies Jellyfin 12.2.0 and a fatal cache
capacity check: the fixture's 128 MiB cache tmpfs was below its required 2 GiB
free space. The data path had already passed with ample space. The swap-limit
warning was not this fatal error, and increasing the readiness timeout would
not address it.

The launcher now binds a new empty `cache` directory inside the exclusive lab
instead of mounting a small cache tmpfs. This exposes the backing filesystem's
actual free space without reserving gigabytes of RAM or disabling the server's
capacity check. Media/root read-only flags, dropped capabilities, memory/CPU/PID
limits, isolated networking, deadlines and new-ID-only restart/cleanup remain.
The [upstream storage helper](https://github.com/jellyfin/jellyfin/blob/master/Jellyfin.Server.Implementations/StorageHelpers/StorageHelper.cs)
checks data, cache and program-data space; those fixture paths now all use the
new disk-backed configuration/cache area. Temp is separate and remains bounded.
Installed-version behavior after this fix still requires a fresh fixture run.
Retain the failed lab and do not resume its partially initialized server.

### Startup succeeds; fixture authorization corrected

After the cache change, Tower's fresh fixture stayed running, was not OOM-killed,
and reached library setup, which returned HTTP 401. This is not an accepted
read-only/protection result. Inspection found that the fixture's Authorization
header contained client metadata without a Token field while X-Emby-Token held
the session token. The client now includes the same token in both headers,
matching the existing auditor transport pattern, and validates token syntax
before dispatch. A request-level test simulates Authorization taking precedence
and verifies one dispatch, not a repeated setup write. Twenty focused local
protocol/policy tests pass. A new fixture must verify actual installed-server
acceptance; the partially initialized previous lab is retained, never resumed.

### Tower acceptance

The fresh `jellyfin-ro.s4hBBv` lab passed with cached Jellyfin 12.2.0 image
`sha256:b603f4b6dede2e060e8bb34e2dc5234926c1ced89d856f227c4a58749719b2a9`.
Both initial and post-restart checks read fresh protection/favorite signals,
received EROFS for the fixed media write, and verified unchanged fixture bytes.
This accepts the tested read-only compatibility path. Production writer
exclusion, NFS clients and administrative restart fencing remain unverified.
