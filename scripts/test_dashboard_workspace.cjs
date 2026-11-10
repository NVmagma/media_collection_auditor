/* Test browser interactions with locally supplied responses and test data. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('../tests/dashboard-browser/node_modules/playwright');
const root = path.resolve(__dirname, '..');
const file = process.argv[2];
if (!file) throw Error('Pass the synthetic page rendered by tests/dashboard_workspace_case.py');
(async () => {
  const browser = await chromium.launch({headless: true});
  try {
    const page = await browser.newPage({viewport: {width: 1280, height: 1000}});
    const errors = [], posts = [];
    let scanRunning = false;
    let scanBlocked = false;
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/*', route => {
      const request = route.request(), url = new URL(request.url());
      if (url.pathname === '/api/run-status') return route.fulfill({contentType:'application/json',body:JSON.stringify({ok:true,running:scanRunning,queued:false,blocked:scanBlocked,progress:scanRunning?{phase:'jellyfin',checked:128,total:541,library:'Movies',elapsed_seconds:83}:null})});
      if (url.pathname === '/api/poster') return route.fulfill({contentType:'image/png',body:fs.readFileSync(path.join(root,'unraid/assets/Media_Collection_Auditor_Badge.png'))});
      if (request.method() !== 'GET') {
        posts.push(request.method());
        if (url.hostname==='fixture.invalid' && url.pathname==='/api/run-now') {
          assert.deepEqual(JSON.parse(request.postData()),{run_live_scan:true});
          scanRunning = true;
          return route.fulfill({status:202,contentType:'application/json',body:JSON.stringify({ok:true,message:'Synthetic live request queued; no worker connected.'})});
        }
      }
      const assets = {'/': [url.searchParams.get('role') === 'live' ? file + '.live.html' : url.searchParams.get('role') === 'admin' ? file + '.admin.html' : file, 'text/html'], '/review': [file + '.review.html', 'text/html'],
        '/static/style.css': [path.join(root, 'app/static/style.css'), 'text/css'],
        '/static/dashboard.js': [path.join(root, 'app/static/dashboard.js'), 'text/javascript'],
        '/static/auditor-badge.png': [path.join(root, 'unraid/assets/Media_Collection_Auditor_Badge.png'), 'image/png']};
      const asset = url.hostname === 'fixture.invalid' && assets[url.pathname];
      return asset ? route.fulfill({body: fs.readFileSync(asset[0]), contentType: asset[1]}) : route.fulfill({status: 404, body: ''});
    });
    await page.goto('http://fixture.invalid/');
    assert.equal(await page.locator('.sidebar [data-workspace]').count(), 6);
    assert.equal(await page.locator('.topbar').count(), 0);
    assert.equal(await page.locator('.sidebar').evaluate(el => el.getBoundingClientRect().left), 0);
    async function section(name) {
      // Review opens a new page. Wait for its deferred navigation setup
      // before checking the page.
      await page.waitForFunction(expected => {
        const visible=Array.from(document.querySelectorAll('[data-panel]'))
          .filter(el => getComputedStyle(el).display !== 'none').map(el => el.dataset.panel);
        return visible.length===1 && visible[0]===expected;
      },name,{timeout:5000});
      const visible = await page.locator('[data-panel]').evaluateAll(elements =>
        elements.filter(el => getComputedStyle(el).display !== 'none').map(el => el.dataset.panel));
      assert.deepEqual(visible, [name]);
    }
    await section('Overview');
    assert.equal(await page.locator('#library-toolbar').isVisible(), false);
    assert.equal(await page.locator('#clock-coverage').count(), 0);
    await page.locator('a[href="/review#clock-coverage"]').click();
    await section('Review');
    assert.equal(new URL(page.url()).pathname, '/review');
    assert.equal(await page.locator('#clock-coverage').getAttribute('open'), '');
    assert.equal(await page.locator('[data-workspace="Review"]').getAttribute('aria-current'), 'page');
    await page.locator('[data-workspace="Overview"]').click();
    await section('Overview');
    assert.equal(await page.locator('#clock-coverage').count(), 0);
    await page.locator('[data-open-title="Summer Frontier (2026)"]').click();
    await section('Movies');
    assert.equal(await page.locator('[data-stage-panel="Movies:Holding"]').isVisible(), true);
    assert.equal(await page.locator('#inspector-title').textContent(), 'Summer Frontier (2026)');
    await page.locator('[data-workspace="Overview"]').click();
    await page.locator('[data-open-title="Lantern House (2026)"]').click();
    await section('TV Shows');
    assert.equal(await page.locator('#inspector-title').textContent(), 'Lantern House (2026)');
    await page.locator('[data-workspace="Overview"]').click();
    await page.locator('[data-open-workspace="History"]').first().click();
    await section('History');
    assert.equal(await page.locator('.history-entry:visible').count(), 5);
    const decisions=page.locator('.history-entry:visible').first().locator('.scan-title-details');
    await decisions.locator('summary').click();
    assert.match(await decisions.innerText(), /Still inside the Waiting period/);
    assert.match(await decisions.innerText(), /Proposed; not completed/);
    assert.match(await page.locator('#history-page-status').textContent(), /Showing 1–5 of 7/);
    await page.locator('#history-next').click();
    assert.equal(await page.locator('.history-entry:visible').count(), 2);
    await page.locator('#history-previous').click();
    await page.locator('#history-filter').selectOption('review');
    assert.equal(await page.locator('.history-entry:visible').count(), 2);
    assert.equal(await page.locator('#history-next').isDisabled(), true);
    await page.locator('#history-filter').selectOption('unknown');
    assert.equal(await page.locator('#history-no-results').isVisible(), true);
    await page.locator('#history-filter').selectOption('all');
    await page.locator('.history-entry:visible details summary').first().click();
    assert.equal(await page.locator('.history-entry:visible details').first().getAttribute('open'), '');
    await page.locator('[data-workspace="Audit Preview"]').click();
    assert.match(await page.locator('[data-panel="Audit Preview"]').textContent(), /Timer estimates · not scan results/);
    assert.match(await page.locator('[data-panel="Audit Preview"]').textContent(), /Per-title decisions are shown when recorded/);
    await page.locator('[data-workspace="Overview"]').click();
    await page.locator('[data-open-library="Movies"]').click();
    await page.locator('[data-stage-tab="Movies:Waiting"]').click();
    await page.locator('[data-workspace="Overview"]').click();

    await page.locator('[data-workspace="Library"]').click();
    await section('Movies');
    assert.equal(await page.locator('#library-toolbar').isVisible(), true);
    assert.equal(await page.locator('.run-cards').isVisible(), false);
    const movieStage = page.locator('[data-stage-panel="Movies:Waiting"]');
    const inventoryCount = await page.locator('[data-stage-tab="Movies:Waiting"]').textContent();
    await page.locator('#library-search').fill('QUIET');
    assert.match(await page.locator('#library-results').textContent(), /Showing 1 of 2/);
    assert.equal(await movieStage.locator('tbody [data-media-title]:not(.library-filtered-out)').count(), 1);
    await movieStage.locator('tbody [data-media-title]:not(.library-filtered-out) .inspect-title').click();
    assert.equal(await page.locator('#title-inspector').isVisible(), true);
    assert.equal(await page.locator('#inspector-title').textContent(), 'The Quiet Orbit (2026)');
    assert.equal(await page.locator('#inspector-since').textContent(), '10/01/2026 11:30');
    assert.match(await page.locator('#inspector-explanation').textContent(), /Unknown \/ not matched/);
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#title-inspector').isVisible(), false);
    assert.equal(await page.evaluate(() => document.activeElement.classList.contains('inspect-title')), true);
    await page.locator('#library-search').fill('does not exist');
    assert.equal(await page.locator('#library-no-matches').isVisible(), true);
    assert.equal(await page.locator('[data-stage-tab="Movies:Waiting"]').textContent(), inventoryCount);
    await page.locator('#library-search').fill('');
    await page.locator('#library-sort').selectOption('desc');
    assert.equal(await movieStage.locator('tbody [data-media-title]').first().getAttribute('data-media-title'), 'The Quiet Orbit (2026)');
    await page.locator('#library-sort').selectOption('asc');
    const escapedRow = movieStage.locator('tbody [data-media-title]').first();
    assert.equal(await escapedRow.getAttribute('data-media-title'), 'A & B <Moon> (2026)');
    await escapedRow.locator('.inspect-title').click();
    assert.equal(await page.locator('#inspector-title').textContent(), 'A & B <Moon> (2026)');
    assert.equal(await page.locator('#inspector-title moon').count(), 0);
    await page.locator('#close-inspector').click();

    await page.locator('[data-tab="TV Shows"]').click();
    await section('TV Shows');
    await page.locator('[data-stage-tab="TV:Holding"]').click();
    assert.equal(await page.locator('[data-stage-panel="TV:Holding"]').isVisible(), true);
    const fullShows = page.getByRole('region', {name: /Full Shows Leaving Soon/});
    const staged = page.getByRole('region', {name: /Seasons Leaving Soon/});
    assert.match(await fullShows.locator('tbody').innerText(), /Harbor Nights/);
    assert.match(await staged.locator('tbody').innerText(), /Lantern House/);
    await page.locator('[data-view="posters"]').click();
    assert.equal(await staged.locator('table').isVisible(), false);
    const seasonCard = staged.locator('.media-poster-row');
    assert.match(await seasonCard.innerText(), /Lantern House.*Season 1/s);
    assert.match(await seasonCard.locator('img').getAttribute('src'), /\/api\/poster\?library=TV/);
    assert.match(await fullShows.locator('.media-poster-row').innerText(), /Harbor Nights/);
    await page.locator('[data-stage-tab="TV:Waiting"]').click();
    const waiting = page.locator('[data-stage-panel="TV:Waiting"]');
    assert.equal(await waiting.locator('.media-poster-list').isVisible(), true);
    assert.equal(await waiting.locator('.table-wrap').isVisible(), false);
    await page.locator('[data-workspace="Audit Preview"]').click();
    await section('Audit Preview');
    assert.equal(await page.locator('#workspace-title').textContent(), 'Scans');
    assert.equal(await page.locator('#library-toolbar').isVisible(), false);
    await page.locator('[data-workspace="Library"]').click();
    await section('TV Shows');
    await page.locator('[data-workspace="History"]').click();
    await section('History');
    assert.equal(await page.locator('.run-cards').isVisible(), false);
    await page.locator('[data-workspace="Activity"]').click();
    await section('Activity');
    await page.locator('[data-workspace="Overview"]').click();
    await page.locator('[data-open-library="Movies"]').click();
    await section('Movies');
    assert.equal(await page.locator('[data-workspace="Library"]').getAttribute('aria-current'), 'page');
    await page.locator('[data-view="table"]').click();
    await page.reload();
    await section('Overview');
    await page.locator('[data-workspace="Library"]').click();
    assert.equal(await page.locator('[data-view="table"]').getAttribute('aria-pressed'), 'true');
    await page.reload();
    await section('Movies');
    for (const width of [1280, 736, 390, 320]) {
      await page.setViewportSize({width, height: 1000});
      for (const workspace of ['Overview', 'Library', 'Audit Preview', 'Activity', 'History', 'Review']) {
        await page.locator(`[data-workspace="${workspace}"]`).click();
        if (workspace === 'Review') await section('Review');
        if (workspace === 'Library') {
          await page.locator('[data-stage-panel="Movies:Waiting"] tbody .inspect-title').first().click();
          assert.equal(await page.locator('#title-inspector').isVisible(), true);
        }
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true,
          `Horizontal page overflow at ${width}px in ${workspace}`);
      }
    }
    await page.locator('[data-panel="Review"] [data-open-library="TV Shows"]').click();
    await section('TV Shows');
    assert.equal(new URL(page.url()).pathname, '/');
    await page.goto('http://fixture.invalid/?role=admin#Overview');
    assert.equal(await page.locator('#run-now').isVisible(), true);
    for (const [width, height] of [[1280, 1000], [1440, 1000]]) {
      await page.setViewportSize({width, height});
      const measured = await page.evaluate(() => document.documentElement.scrollHeight);
      if (measured > height && process.env.DASHBOARD_SCREENSHOT_DIRECTORY) await page.screenshot({path: path.join(process.env.DASHBOARD_SCREENSHOT_DIRECTORY, 'dashboard-fit.png'), fullPage: true});
      assert.equal(measured <= height, true, `Overview requires ${measured}px at ${width}x${height}`);
    }
    await page.goto('http://fixture.invalid/');
    assert.deepEqual(posts, []);
    await page.goto('http://fixture.invalid/?role=live#Overview');
    assert.equal(await page.locator('#run-now').textContent(),'Run Live Scan Now');
    const dialog=page.waitForEvent('dialog');
    const click=page.locator('#run-now').click();
    const confirmation=await dialog;
    assert.match(confirmation.message(),/60 minutes apart/);
    await confirmation.accept();await click;
    await page.waitForFunction(() => document.getElementById('run-now').textContent === 'Scan running…');
    assert.match(await page.locator('#run-result').textContent(), /Checking Jellyfin protection.*128 of 541.*Elapsed 1m 23s/);
    assert.equal(await page.locator('#run-now').isDisabled(),true);
    scanRunning = false;
    scanBlocked = true;
    await page.waitForFunction(() => document.getElementById('run-now').textContent === 'Review required',{},{timeout:10000});
    assert.equal(await page.locator('#run-now').isDisabled(),true);
    assert.match(await page.locator('#run-result').textContent(),/previous attempt is historical/);
    scanBlocked = false;
    await page.waitForFunction(() => !document.getElementById('run-now').disabled,{},{timeout:10000});
    assert.deepEqual(posts,['POST']);
    await page.goto('http://fixture.invalid/');
    assert.deepEqual(errors, []);
    if (process.env.DASHBOARD_SCREENSHOT_DIRECTORY) {
      await page.setViewportSize({width: 1280, height: 1000});
      await page.locator('[data-workspace="Overview"]').click();
      await page.screenshot({path: path.join(process.env.DASHBOARD_SCREENSHOT_DIRECTORY, 'dashboard-overview.png'), fullPage: true});
      await page.locator('[data-workspace="Audit Preview"]').click();
      await page.screenshot({path: path.join(process.env.DASHBOARD_SCREENSHOT_DIRECTORY, 'dashboard-scans.png'), fullPage: true});
      await page.locator('[data-workspace="History"]').click();
      await page.screenshot({path: path.join(process.env.DASHBOARD_SCREENSHOT_DIRECTORY, 'dashboard-history.png'), fullPage: true});
      await page.locator('[data-workspace="Review"]').click();
      await page.screenshot({path: path.join(process.env.DASHBOARD_SCREENSHOT_DIRECTORY, 'dashboard-review.png'), fullPage: true});
      await page.locator('[data-workspace="Library"]').click();
      await page.locator('[data-stage-panel="Movies:Waiting"] tbody .inspect-title').first().click();
      await page.screenshot({path: path.join(process.env.DASHBOARD_SCREENSHOT_DIRECTORY, 'dashboard-library.png'), fullPage: true});
      await page.setViewportSize({width: 390, height: 1000});
      await page.screenshot({path: path.join(process.env.DASHBOARD_SCREENSHOT_DIRECTORY, 'dashboard-mobile.png'), fullPage: true});
    }
    console.log(JSON.stringify({status: 'dashboard_workspace_browser_verified', widths: [1280,736,390,320],
      navigation_and_view_state_verified: true, separate_review_page_verified: true,
      desktop_overview_fits: [[1280,1000],[1440,1000]], history_filter_pagination_verified: true, external_requests_performed: false, production_changes_performed: false}));
  } finally {await browser.close();}
})().catch(error => {console.error(error); process.exitCode = 1;});
