/* Synthetic backup summaries only; POSTs are observed but never dispatched. */
const assert=require('node:assert/strict');const fs=require('fs');const path=require('path');
const {chromium}=require('../tests/dashboard-browser/node_modules/playwright');
(async()=>{const browser=await chromium.launch();try{
  const page=await browser.newPage();const mutations=[],errors=[];
  page.on('pageerror',error=>errors.push(error.message));
  await page.route('**/*',route=>{
    const request=route.request(),url=new URL(request.url());
    if(request.method()!=='GET'){mutations.push(request.method());return route.fulfill({status:409,body:'No real operations in browser fixture.'});}
    if(url.pathname==='/backups')return route.fulfill({contentType:'text/html',body:fs.readFileSync(process.argv[2])});
    const asset={'/static/style.css':'app/static/style.css','/static/auditor-badge.png':'unraid/assets/Media_Collection_Auditor_Badge.png'}[url.pathname];
    return asset?route.fulfill({body:fs.readFileSync(path.resolve(__dirname,'..',asset)),contentType:asset.endsWith('.css')?'text/css':'image/png'}):route.fulfill({status:404,body:''});
  });
  for(const width of [1280,736,390,320]){
    await page.setViewportSize({width,height:1000});await page.goto('http://fixture.invalid/backups');
    assert.equal(await page.locator('tbody tr').count(),5);
    assert.equal(await page.locator('a[aria-label="Backups"]').getAttribute('aria-current'),'page');
    assert.equal(await page.getByRole('button',{name:'Create private backup'}).isVisible(),true);
    assert.equal(await page.locator('button[value=test_restore]').count(),4);
    assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'overflow '+width);
    assert.match(await page.locator('main').textContent(),/same appdata storage, not off-server protection/);
    assert.match(await page.locator('main').textContent(),/No automatic retention or deletion/);
  }
  assert.deepEqual(mutations,[]);assert.deepEqual(errors,[]);
  console.log(JSON.stringify({backup_workspace_browser_verified:true,widths:[1280,736,390,320],production_changes_performed:false}));
}finally{await browser.close();}})().catch(error=>{console.error(error);process.exitCode=1;});
