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
proposal summary and two five-title lists combining enabled movie/TV libraries.
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
