/* Compare local test data without contacting or changing services. */
const assert=require('node:assert/strict');
const fs=require('fs');const path=require('path');
const {chromium}=require('../tests/dashboard-browser/node_modules/playwright');
(async()=>{const browser=await chromium.launch();try{
  const page=await browser.newPage();const mutations=[],errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/*',route=>{
    const request=route.request(),url=new URL(request.url());
    if(request.method()!=='GET')mutations.push(request.method());
    if(url.pathname==='/tracking-review')return route.fulfill({contentType:'text/html',body:fs.readFileSync(process.argv[2])});
    const asset={'/static/style.css':'app/static/style.css','/static/auditor-badge.png':'unraid/assets/Media_Collection_Auditor_Badge.png'}[url.pathname];
    return asset?route.fulfill({body:fs.readFileSync(path.resolve(__dirname,'..',asset)),contentType:asset.endsWith('.css')?'text/css':'image/png'}):route.fulfill({status:404,body:''});
  });
  for(const width of [1280,736,390,320]){
    await page.setViewportSize({width,height:1000});await page.goto('http://fixture.invalid/tracking-review');
    assert.equal(await page.locator('tbody tr').count(),25);
    assert.equal(await page.locator('a[aria-label="Tracking Review"]').getAttribute('aria-current'),'page');
    assert.equal(await page.locator('input[name=q]').isVisible(),true);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'overflow '+width);
    assert.match(await page.locator('main').textContent(),/does not prove media was deleted/);
    assert.equal(await page.locator('a[href="/arr-imports"]').count(),1);
  }
  assert.deepEqual(mutations,[]);assert.deepEqual(errors,[]);
  console.log(JSON.stringify({tracking_review_browser_verified:true,widths:[1280,736,390,320],production_changes_performed:false}));
}finally{await browser.close();}})().catch(error=>{console.error(error);process.exitCode=1;});
