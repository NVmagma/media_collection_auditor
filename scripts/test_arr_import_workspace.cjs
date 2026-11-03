/* Browser-only fixtures: never contact Arr, Docker, production paths or services. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('../tests/dashboard-browser/node_modules/playwright');
const root = path.resolve(__dirname, '..');
(async () => {
  const browser = await chromium.launch({headless:true});
  try {
    const page = await browser.newPage({viewport:{width:1280,height:1000}});
    const errors = [], requests = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/*', async route => {
      const request = route.request(), url = new URL(request.url());
      assert.equal(url.hostname,'fixture.invalid');
      if (url.pathname.startsWith('/api/arr-import/')) {
        requests.push(url.pathname);
        let result;
        if (request.method()==='POST') assert.equal(JSON.parse(request.postData()).csrf,'synthetic-csrf');
        if (url.pathname.endsWith('/options')) result = {quality_profiles:[{id:2,name:'Existing HD'}],folders:['Existing Show'],folders_truncated:false};
        else if (url.pathname.endsWith('/lookup')) result = {matches:[{provider_id:100,title:'Existing <Show>',year:2020}],truncated:false};
        else if (url.pathname.endsWith('/review')) {
          assert.deepEqual(JSON.parse(request.postData()),{csrf:'synthetic-csrf',library:'TV',folder:'Existing Show',provider_id:100,quality_profile_id:2});
          result = {review_fingerprint:'a'.repeat(64),title:'Existing <Show>',year:2020,
            service:'sonarr',stage:'Waiting',path:'/media/TV/Existing Show',quality_profile:'Existing HD',media_files:12};
        } else if (url.pathname.endsWith('/apply')) {
          assert.deepEqual(JSON.parse(request.postData()),{csrf:'synthetic-csrf',review_fingerprint:'a'.repeat(64)});
          result = {status:'existing_media_import_verified'};
        } else throw Error('Unexpected import endpoint');
        return route.fulfill({contentType:'application/json',body:JSON.stringify({ok:true,...result})});
      }
      const assets = {'/arr-imports':[process.argv[2],'text/html'],
        '/static/style.css':[path.join(root,'app/static/style.css'),'text/css'],
        '/static/arr-imports.js':[path.join(root,'app/static/arr-imports.js'),'text/javascript'],
        '/static/auditor-badge.png':[path.join(root,'unraid/assets/Media_Collection_Auditor_Badge.png'),'image/png']};
      const asset = assets[url.pathname];
      return asset ? route.fulfill({body:fs.readFileSync(asset[0]),contentType:asset[1]}) : route.fulfill({status:404,body:''});
    });
    await page.goto('http://fixture.invalid/arr-imports');
    assert.equal(await page.locator('.sidebar').evaluate(el=>el.getBoundingClientRect().left),0);
    assert.equal(await page.locator('#import-apply').isDisabled(),true);
    assert.equal(requests.length,0); // Opening the page never imports or fetches Arr.
    await page.locator('#import-library').selectOption('TV');
    await page.locator('#import-load').click();
    await page.waitForFunction(()=>document.getElementById('import-profile').options.length===2);
    await page.locator('#import-profile').selectOption('2');
    await page.locator('#import-folder').fill('Existing Show');
    await page.locator('#import-search').fill('Existing Show');
    await page.locator('#import-find').click();
    await page.waitForFunction(()=>document.getElementById('import-match').options.length===2);
    await page.locator('#import-match').selectOption('100');
    await page.locator('#import-review').click();
    await page.waitForFunction(()=>!document.getElementById('import-apply').disabled);
    assert.match(await page.locator('#import-description').textContent(),/Existing <Show>/);
    assert.match(await page.locator('#import-summary').textContent(),/Monitoring: Off/);
    if (process.env.IMPORT_SCREENSHOT_FILE) await page.screenshot({path:process.env.IMPORT_SCREENSHOT_FILE,fullPage:true});
    assert.equal(requests.filter(p=>p.endsWith('/apply')).length,0);
    await page.locator('#import-folder').fill('Other');
    assert.equal(await page.locator('#import-summary').isVisible(),false);
    assert.equal(await page.locator('#import-apply').isDisabled(),true);
    await page.locator('#import-folder').fill('Existing Show');
    await page.locator('#import-review').click();
    await page.waitForFunction(()=>!document.getElementById('import-apply').disabled);
    await page.locator('#import-apply').click();
    await page.waitForFunction(()=>document.getElementById('import-status').textContent.startsWith('Arr registration verified'));
    assert.equal(requests.filter(p=>p.endsWith('/apply')).length,1);
    assert.equal(await page.locator('#import-apply').isDisabled(),true);
    assert.match(await page.locator('#import-status').textContent(),/may still be scanning/);
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth),true);
    assert.deepEqual(errors,[]);
    console.log('Existing-media import browser review and explicit apply verified (synthetic only).');
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
