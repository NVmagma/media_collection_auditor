/* Synthetic recorded data only; no production services or mutations. */
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require('../tests/dashboard-browser/node_modules/playwright');
(async()=>{
  const browser=await chromium.launch();
  try {
    const page=await browser.newPage();const mutations=[];const errors=[];
    page.on('pageerror',error=>errors.push(error.message));
    await page.route('**/*',route=>{
      const request=route.request(),url=new URL(request.url());
      if(request.method()!=='GET')mutations.push(request.method());
      if(url.pathname==='/cleanup-review') {
        const view=url.searchParams.get('view')||'observing';
        assert.ok(['observing','blocked','quarantined'].includes(view));
        return route.fulfill({contentType:'text/html',body:fs.readFileSync(process.argv[2]+'.'+view+'.html')});
      }
      const asset={'/static/style.css':'app/static/style.css','/static/auditor-badge.png':'unraid/assets/Media_Collection_Auditor_Badge.png'}[url.pathname];
      return asset?route.fulfill({body:fs.readFileSync(path.resolve(__dirname,'..',asset)),contentType:asset.endsWith('.css')?'text/css':'image/png'}):route.fulfill({status:404,body:''});
    });
    for(const width of [1280,736,390,320]) {
      await page.setViewportSize({width,height:1000});await page.goto('http://fixture.invalid/cleanup-review');
      assert.equal(await page.locator('tbody tr').count(),25);
      assert.equal(await page.locator('a[aria-label="Cleanup Review"]').getAttribute('aria-current'),'page');
      assert.equal(await page.locator('input[name=q]').isVisible(),true);
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'overflow at '+width);
      assert.match(await page.locator('tbody').textContent(),/12.0 \/ 24 hours/);
    }
    await page.goto('http://fixture.invalid/cleanup-review?view=quarantined');
    assert.match(await page.locator('tbody').textContent(),/\/media\/\.auditor-orphans\/bbbb/);
    assert.match(await page.locator('main').textContent(),/historical receipts, not verified current inventory/);
    await page.goto('http://fixture.invalid/cleanup-review?view=blocked');
    assert.match(await page.locator('main').textContent(),/partial or unavailable/);
    assert.deepEqual(mutations,[]);assert.deepEqual(errors,[]);
    console.log(JSON.stringify({cleanup_review_browser_verified:true,widths:[1280,736,390,320],production_changes_performed:false}));
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
