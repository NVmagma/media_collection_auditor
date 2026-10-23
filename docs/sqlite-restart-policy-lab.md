# Disposable Docker restart-policy check

Run on Tower from the feature/sqlite checkout:

```sh
bash scripts/sqlite_restart_policy_lab.sh /mnt/user/sql_test
```

Uses only the cached pinned Python image, a newly created labeled container and
new lab files. It does not restart Docker, publish ports, mount a Docker socket,
or control existing services. Fixture artifacts remain for review.

The actor increments a startup counter and exits 17 on its process-specific
fixed crash request. With `on-failure:2`, the first crash must cause an automatic
restart. One retry remains available, so the second crash is meaningful. A
controller persists `restart=no` and is then killed. The next actor crash must
leave exit code 17, restart count one, and startup counter two unchanged through
a bounded observation. Cleanup removes only the label-verified new container;
failed cleanup cannot produce the success status. A 90-second process alarm and
two-retry limit bound an orphan actor's lifetime.

Docker documents a successful-start monitoring interval of ten seconds; the
fixture waits eleven seconds before each induced process failure. It does not
use a manual Docker stop as the failure trigger, since a manual stop suppresses
restart policy independently. See [Docker restart policies](https://docs.docker.com/engine/containers/start-containers-automatically/).

This verifies only process-failure policy behavior under a running daemon. It
cannot prevent explicit administrator starts, container recreation, host boot
jobs, external supervisors or other writers. No daemon restart or host reboot
is performed. Production activation, writer exclusion and restart-inhibition
verification stay disabled/false. Actual Docker behavior requires Tower output;
local actor tests alone do not establish it.
