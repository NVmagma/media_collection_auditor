/* Synthetic browser acceptance: no network requests or production state. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('../tests/dashboard-browser/node_modules/playwright');
(async () => {
  const browser = await chromium.launch({headless:true});
  try {
    const page = await browser.newPage();
    const errors=[];
    page.on('pageerror', e => errors.push(e.message));
    await page.route('**/*', route => {
      const url = new URL(route.request().url());
      if (url.pathname === '/integrations') return route.fulfill({contentType:'text/html',body:fs.readFileSync(process.argv[2],'utf8')});
      if (['/static/style.css','/static/integrations.js'].includes(url.pathname)) return route.fulfill({contentType:url.pathname.endsWith('.js')?'application/javascript':'text/css',body:fs.readFileSync(path.join(__dirname,'../app',url.pathname),'utf8')});
      return route.abort();
    });
    await page.goto('http://fixture.invalid/integrations');
    assert.equal(await page.locator('#integration-base').inputValue(), 'http://fixture.invalid');
    assert.equal(await page.locator('input[type=password]').count(),0);
    assert.equal(await page.locator('form').count(),0);
    assert.equal(await page.locator('[data-copy]').count(),5);
    await page.evaluate(() => { Object.defineProperty(navigator,'clipboard',{value:{writeText:async value => { window.copied=value; }}, configurable:true}); });
    await page.locator('[data-copy="path-leaving-soon-TV"]').click();
    assert.equal(await page.evaluate(() => window.copied), '/api/v1/titles/leaving-soon');
    assert.equal(await page.locator('#integration-copy-status').textContent(),'Copied.');
    for (const width of [1440,900,390,320]) {
      await page.setViewportSize({width,height:1000});
      const overflow = await page.evaluate(() => Array.from(document.querySelectorAll('body *')).filter(e => e.getBoundingClientRect().right > innerWidth + 1).map(e => ({tag:e.tagName,cls:e.className,width:e.getBoundingClientRect().width})).slice(0,8));
      assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),true, 'horizontal overflow at '+width+' '+JSON.stringify(overflow));
    }
    assert.deepEqual(errors,[]);
    console.log(JSON.stringify({status:'integration_setup_browser_verified',copy_verified:true,credential_inputs:0,production_services_changed:false}));
  } finally { await browser.close(); }
})().catch(error => {console.error(error); process.exitCode=1;});
