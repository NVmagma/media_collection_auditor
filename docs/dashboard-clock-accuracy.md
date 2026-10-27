# Dashboard clock accuracy (development)

The dashboard reads lifecycle dates from the selected tracking backend. It does
not create clocks from folder modification times or borrow a date from another
stage. Movie keys and `TV/` keys remain separate; folder names are matched exactly.

Lifecycle rows now display `MM/DD/YYYY HH:MM`. Naive timestamps retain their
recorded local wall time; aware timestamps retain their offset and age calculations
use that timezone. This fixes removal-stage ages that previously became unknown
when an offset-aware clock was subtracted from a naive current time. Missing dates
say **Not yet tracked**, malformed dates say **Invalid saved date**, and future
clocks do not receive invented elapsed days or deadline candidates.

The last finished attempt and next scheduled run use the configured daily-run
zone (or `TZ`) when the stored observation includes a timezone. Naive observations
are not converted to an assumed timezone. An absent process observation remains
explicitly unrecorded rather than being reconstructed from media clocks. These
views do not establish inventory freshness or authorize media operations.

## Redacted current-runtime coverage report

On Tower, run:

```bash
bash scripts/dashboard_clock_coverage_host.sh
```

The wrapper uses the current cached image, read-only inherited media/logs/control
mounts, no network and no Docker socket inside its helper. It refuses unexpected
mounts and image-declared volumes. No service settings, state, media or timestamps
are changed. The helper performs the current packaged SQLite binding validation
before and after reading; it does not select JSON as a fallback for SQLite.

The output contains only library/stage labels and counts: observed folders,
recorded/missing/invalid dates, case-only match candidates, clocks recorded in
another stage, and unmatched tracking records. Unavailable directories are marked
unavailable rather than reported as successfully empty. Case-only candidates are
diagnostic counts, not automatic associations. No titles, filesystem paths,
credentials or clock values are printed. This observation alone cannot authorize
state repair, reset clocks or establish live freshness.

Zero-day Waiting policies remain zero-day estimates rather than being silently
rounded to one day. Invalid duration settings leave estimates unavailable and do
not create dashboard move candidates. These display calculations never change
stored clocks or the worker's safety policy.
