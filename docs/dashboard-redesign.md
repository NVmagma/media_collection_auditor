# Hybrid dashboard redesign

Development branch: `feature/interface-api`. Production is unchanged.

## Implemented increments

- Overview / Library / Scans / Activity / History navigation; Settings remains an
  administrator-only link. The existing icon and dark appearance are retained.
- Movie/TV selection and table/poster controls appear only in Library. Run metrics
  appear in Overview and History; the existing preview request control remains
  governed by the same backend mode and administrator checks.
- Separate saved tracking totals from filesystem stage counts. Missing tracking
  produces unavailable totals, not healthy zeroes.
- Local title search and alphabetical sorting within each library. Stage totals
  continue to show the unfiltered inventory; the results line reports matching
  folders in the selected stage. Search applies to the rendered page snapshot;
  it does not collect data, refresh protection information or initialize clocks.
- A read-only Details panel reuses the already-rendered stage explanation,
  saved date and protection/decision text. Unknown information remains unknown.
  Keyboard users can close with Escape or Close and return to the triggering
  button. The inspector stacks above the list on smaller screens.

The first shell/Library preview received positive user feedback. Overview now
adds read-only attention items, a compact scheduler summary, a latest-attempt
proposal summary and two three-title lists combining enabled movie/TV libraries.
Selecting a list title opens its matching Library stage and Details panel. Poster
requests use the existing authenticated image route, with an inert fallback.
The new lists use the already enriched inventory; they do not rescan directories
or request protection data. Waiting sorts by recorded elapsed days (then title);
Holding sorts by the existing estimated calendar date. Unknown dates sort last,
unavailable tracking suppresses the lists, and partial directory coverage stays
explicit. Stage dates and tracking records are never initialized by this view.

Compact Library media rows, additional filters, scan-history redesign and
active/pending Settings redesign remain upcoming.
The Scans workspace currently contains the existing saved-date deadline estimate,
not a reconstructed live scan or a promise of future media actions.

## Automated verification

The focused dashboard/security/tracking tests and API/manual-preview tests passed
on Linux (61 + 75 tests). A development-only pinned Playwright runner checks the
real template and script in Chromium at 1280, 736, 390 and 320px. Requests are
intercepted with synthetic local assets; no service credentials are used. It
checks navigation, stage/view state, query matching, sort order, literal special
characters in titles, inspector focus/close behavior and page overflow.

```bash
python -B -m pytest -q tests/test_dashboard_workspace.py tests/test_web_security.py
python -B tests/dashboard_workspace_case.py /tmp/dashboard-workspace.html
npm ci --prefix tests/dashboard-browser --ignore-scripts --no-audit --no-fund
tests/dashboard-browser/node_modules/.bin/playwright install chromium --only-shell
npm test --prefix tests/dashboard-browser -- /tmp/dashboard-workspace.html
```

Python commands need `PYTHONPATH=.:app:tests` and a test-only `WEB_SESSION_SECRET`.
Node/Playwright are development dependencies, excluded from production images.
GitHub Actions acceptance is pending while the account billing limit blocks jobs.

## Disposable visual preview on Tower

```bash
bash scripts/dashboard_workspace_lab.sh /mnt/user/sql_test
```

The helper reads only the existing auditor's cached image identity to select its
Python/Flask runtime. It archives committed UI/fixture sources into a **new** lab
folder, mounts that folder read-only and starts a new fixture container on host
port 8091. It never mounts production appdata, media or the Docker socket, copies
no production environment, and never starts an auditor worker. All title/state
inputs are synthetic. The preview intentionally has no settings/action/API routes.
POST requests are refused. The title/Jellyfin destinations and unavailable fixture
posters are not a production navigation test.

Open the returned preview URL. Check Overview, Library movie/TV/stage switching,
search, sort, Details and mobile layout. Keep the production auditor and its saved
Unraid template unchanged. This verifies checkout UI behavior with a cached
runtime; it is not acceptance of a newly published image or its release binding.
If 8091 is occupied, pass another unused port as the second argument; the helper
will not stop an existing service to claim the port.

The server exits after fifteen minutes. Its stopped container and lab files are
retained. Use the exact returned container ID to remove only that fixture when
finished; no automatic production restoration or changes occur.

Overview follow-up verification: 148 focused Linux checks passed. Chromium checks
include coverage expansion, movie/TV title-to-inspector navigation and mobile
overflow, alongside the existing search/sort/focus checks. The synthetic server
also served the Overview over private HTTP while rejecting action requests.
The Tower visual review for this Overview increment is pending.

## Dedicated Review page and compact Overview

Coverage and collection diagnostics now live at `/review`, behind the same
sign-in and preview-binding checks as Dashboard. Overview does not embed those
diagnostic sections or expand them in place. Review coverage/findings links
navigate to the separate page; both sections are open there. Library navigation
from Review returns to the main Library workspace.

Overview contains brief finding summaries and three titles per list; detailed
explanations remain on Review. The compact desktop layout is browser-tested at
1280×1000 and 1440×1000 with administrator controls visible and no page scroll for
the representative synthetic collection. This is not a fixed-height/clipped view:
phone layouts stack, and critical errors or unusually long content may still
require scrolling. The full Library and Review content remain available.

## Scans and process-local History

The SQLite Scans workspace now separates current running/queued/waiting/blocked
observations, the latest recorded attempt, and the existing saved-date timer
estimates. A missed daily slot is not presented as a completed scan. Run Preview
retains its existing administrator and backend-mode checks.

History renders a scalar-only projection of the scheduler's existing records,
with result filters, five-entry pages and expandable outcome details. Preview
proposals, discovery changes, completed moves and Arr updates remain distinct.
Missing counts stay unknown. Valid aware start/finish times provide durations;
missing/reversed/naive times cannot certify completion. Times display using the
configured dashboard zone where available. Mode comes from each record, not
from current settings; an absent mode is not labeled Live. Raw exceptions,
unknown keys, source payloads and unrecognized reason text are not forwarded to
the new SQLite view. The legacy JSON history table remains compatible.

No new scheduler history is collected or persisted. SQLite history is still
bounded to the current process (up to 100 entries) and resets after restart.
Per-title proposal manifests and skipped/blocked title counts/reasons are not
retained in these observations; the UI explicitly says they are not recorded.
It does not infer them from folder inventory or action-log totals, retry a run,
reconcile an intent or authorize any media operation.

The disposable preview includes synthetic completed previews, a recorded live
outcome and failed/uncertain outcomes to exercise the labels and filters. These
are illustrative records; no actual scan or media operation took place.

## Settings status and local drafts

The Settings page separates active field values, the saved request and explicit
application/recovery into three status cards. Only allowlisted field names are
shown for requested changes; pending values and credentials are not projected.
The editor begins with the existing values. Local changes receive an unsaved
indicator; edits and indicator text are not autosaved or put in browser storage.
Preview Settings has one Apply Requested Settings action. It validates and stages
the submitted edits, then applies that exact request through the guarded transaction.
With unchanged edits, only the explicitly rendered ready request digest can be
applied. Concurrent replacement requests are never substituted. The separate
Save Requested Changes button and typed acknowledgement are removed in preview;
backend origin, administrator, binding, locking, validation and restore checks remain.

Recovery retains the disabled editor and explicit Restore form outside it.
Stale/review/resubmit states allow submitting newly reviewed edits without adopting
a retained request digest. Recovery offers Restore only. Connection tests keep using
the active server endpoint; typed draft values are not sent by those tests.
The legacy non-preview save flow remains supported.

The synthetic Tower server offers `/settings` and
`/settings?scenario=recovery` (also `stale`, `clean`, `review`, `resubmit`). These
are generated demonstration states, not the host's actual settings. All POST
submissions are refused by that fixture server. Use placeholder edits only;
actual apply/restore behavior is covered separately by disposable backend tests.

Settings verification: 128 focused Linux tests and 8 subtests passed, including
application/recovery/security and Docker runtime checks. Real Chromium checks
cover local draft counts, credential masking, all six status states, category
switching, the single Apply form submission and 1440/900/390/320px widths. A private HTTP fixture check verified the
page and script while refusing application. Existing Dashboard browser checks
still pass. User visual acceptance is pending; no production service changed.

## Shared application shell follow-up (2026-10-28)

User requests consistent navigation and visual treatment across Dashboard,
Settings and other application pages. Use Settings as the reference: main
sections in a left sidebar and the selected content on the right. Preserve
clickable dashboard sections and the separate Review page, compact desktop
layout and accessible/mobile navigation. Unify typography, spacing, cards,
active/visited states and page headers rather than restyling one page alone.
Live move readiness takes priority; this shell work follows it.
