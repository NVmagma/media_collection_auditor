/* Real-browser interaction acceptance; every HTTP response is local synthetic input. */
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
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/*', route => {
      const request = route.request(), url = new URL(request.url());
      if (request.method() !== 'GET') posts.push(request.method());
      const assets = {'/': [file, 'text/html'],
        '/static/style.css': [path.join(root, 'app/static/style.css'), 'text/css'],
        '/static/dashboard.js': [path.join(root, 'app/static/dashboard.js'), 'text/javascript'],
        '/static/auditor-badge.png': [path.join(root, 'unraid/assets/Media_Collection_Auditor_Badge.png'), 'image/png']};
      const asset = url.hostname === 'fixture.invalid' && assets[url.pathname];
      return asset ? route.fulfill({body: fs.readFileSync(asset[0]), contentType: asset[1]}) : route.fulfill({status: 404, body: ''});
    });
    await page.goto('http://fixture.invalid/');
    async function section(name) {
      const visible = await page.locator('[data-panel]').evaluateAll(elements =>
        elements.filter(el => getComputedStyle(el).display !== 'none').map(el => el.dataset.panel));
      assert.deepEqual(visible, [name]);
    }
    await section('Overview');
    assert.equal(await page.locator('#library-toolbar').isVisible(), false);
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
    await page.locator('[data-view="posters"]').click();
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
    assert.equal(await page.locator('.run-cards').isVisible(), true);
    await page.locator('[data-workspace="Activity"]').click();
    await section('Activity');
    await page.locator('[data-workspace="Overview"]').click();
    await page.locator('[data-open-library="Movies"]').click();
    await section('Movies');
    assert.equal(await page.locator('[data-workspace="Library"]').getAttribute('aria-pressed'), 'true');
    await page.locator('[data-view="table"]').click();
    await page.reload();
    await section('Overview');
    await page.locator('[data-workspace="Library"]').click();
    assert.equal(await page.locator('[data-view="table"]').getAttribute('aria-pressed'), 'true');
    for (const width of [1280, 736, 390, 320]) {
      await page.setViewportSize({width, height: 1000});
      for (const workspace of ['Overview', 'Library', 'Audit Preview', 'Activity', 'History']) {
        await page.locator(`[data-workspace="${workspace}"]`).click();
        if (workspace === 'Library') {
          await page.locator('[data-stage-panel="Movies:Waiting"] tbody .inspect-title').first().click();
          assert.equal(await page.locator('#title-inspector').isVisible(), true);
        }
        assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), true,
          `Horizontal page overflow at ${width}px in ${workspace}`);
      }
    }
    assert.deepEqual(posts, []);
    assert.deepEqual(errors, []);
    if (process.env.DASHBOARD_SCREENSHOT_DIRECTORY) {
      await page.setViewportSize({width: 1280, height: 1000});
      await page.locator('[data-workspace="Overview"]').click();
      await page.screenshot({path: path.join(process.env.DASHBOARD_SCREENSHOT_DIRECTORY, 'dashboard-overview.png'), fullPage: true});
      await page.locator('[data-workspace="Library"]').click();
      await page.locator('[data-stage-panel="Movies:Waiting"] tbody .inspect-title').first().click();
      await page.screenshot({path: path.join(process.env.DASHBOARD_SCREENSHOT_DIRECTORY, 'dashboard-library.png'), fullPage: true});
      await page.setViewportSize({width: 390, height: 1000});
      await page.screenshot({path: path.join(process.env.DASHBOARD_SCREENSHOT_DIRECTORY, 'dashboard-mobile.png'), fullPage: true});
    }
    console.log(JSON.stringify({status: 'dashboard_workspace_browser_verified', widths: [1280,736,390,320],
      navigation_and_view_state_verified: true, external_requests_performed: false, production_changes_performed: false}));
  } finally {await browser.close();}
})().catch(error => {console.error(error); process.exitCode = 1;});
