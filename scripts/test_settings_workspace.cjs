/* Synthetic Settings browser checks; no actual settings application or service access. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('../tests/dashboard-browser/node_modules/playwright');
const root = path.resolve(__dirname, '..');
const prefix = process.argv[2];
if (!prefix) throw Error('Pass the synthetic output prefix from tests/settings_workspace_case.py');
(async () => {
  const browser = await chromium.launch({headless:true});
  try {
    const page = await browser.newPage({viewport:{width:1440,height:1000}});
    const errors=[],posts=[];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/*', route => {
      const req=route.request(),url=new URL(req.url());
      if(req.method()!=='GET') {
        posts.push({path:url.pathname,body:req.postData()});
        if(url.hostname==='fixture.invalid' && url.pathname==='/api/test-connection/jellyfin')
          return route.fulfill({contentType:'application/json',body:JSON.stringify({ok:true,message:'Synthetic active connection response'})});
        return route.fulfill({status:405,body:'Synthetic preview: no submissions'});
      }
      const assets={'/static/style.css':['app/static/style.css','text/css'],
        '/static/settings.js':['app/static/settings.js','text/javascript'],
        '/static/auditor-badge.png':['unraid/assets/Media_Collection_Auditor_Badge.png','image/png']};
      if(url.hostname!=='fixture.invalid') return route.abort();
      if(url.pathname==='/settings') {
        const scenario=url.searchParams.get('scenario') || 'ready';
        if(!['ready','recovery','stale','clean','review','resubmit'].includes(scenario)) return route.fulfill({status:400});
        return route.fulfill({contentType:'text/html',body:fs.readFileSync(prefix+'.'+scenario+'.html')});
      }
      const asset=assets[url.pathname];
      return asset ? route.fulfill({contentType:asset[1],body:fs.readFileSync(path.join(root,asset[0]))}) : route.fulfill({status:404});
    });
    await page.goto('http://fixture.invalid/settings');
    assert.equal(await page.locator('#settings-draft-status').textContent(),'No unsaved field edits');
    assert.equal(await page.locator('form[action="/settings/apply"]').count(),1);
    assert.equal(await page.locator('input[name="request_sha256"]').inputValue(),'a'.repeat(64));
    await page.locator('.pending-field-names summary').click();
    assert.match(await page.locator('.pending-field-names').textContent(),/Manage TV Shows/);
    await page.locator('#field-JELLYFIN_HOST_URL').fill('https://edited.example.invalid');
    assert.match(await page.locator('#settings-draft-status').textContent(),/1 unsaved field edit/);
    await page.locator('#field-JELLYFIN_HOST_URL').fill('https://jellyfin.example.invalid');
    assert.equal(await page.locator('.draft-changed').count(),0);
    await page.locator('#field-JELLYFIN_API_TOKEN').fill('typed-test-secret-only');
    assert.equal(await page.locator('body').innerText().then(s=>s.includes('typed-test-secret-only')),false);
    assert.equal(await page.evaluate(()=>JSON.stringify({...localStorage}).includes('typed-test-secret-only')),false);
    await page.locator('[data-tab="Lifecycle"]').click();
    await page.locator('#field-HOLDING_DAYS').fill('11');
    assert.match(await page.locator('#settings-draft-status').textContent(),/2 unsaved field edits/);
    assert.equal(await page.locator('.draft-changed').count(),2);
    await page.locator('#field-HOLDING_DAYS').fill('7');
    await page.locator('[data-tab="Connections"]').click();
    await page.locator('#field-JELLYFIN_API_TOKEN').fill('');
    assert.equal(await page.locator('.draft-changed').count(),0);
    assert.deepEqual(posts,[]);
    await page.locator('[data-test-service="jellyfin"]').click();
    await page.getByText('Synthetic active connection response',{exact:true}).waitFor();
    assert.deepEqual(posts,[{path:'/api/test-connection/jellyfin',body:null}]);
    for(const width of [1440,900,390,320]) {
      await page.setViewportSize({width,height:1000});
      for(const group of ['Connections','Libraries','Lifecycle','Safety','Notifications']) {
        await page.locator(`[data-tab="${group}"]`).click();
        assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,
          `Settings overflow at ${width}px in ${group}`);
      }
    }
    for(const scenario of ['stale','clean','review','resubmit']) {
      await page.goto('http://fixture.invalid/settings?scenario='+scenario);
      assert.equal(await page.locator('form[action="/settings/apply"]').count(),0);
      assert.equal(await page.locator('form[action="/settings/restore"]').count(),0);
      assert.equal(await page.locator('#field-JELLYFIN_API_TOKEN').inputValue(),'');
    }
    await page.goto('http://fixture.invalid/settings?scenario=recovery');
    assert.match(await page.locator('#settings-draft-status').textContent(),/Editing paused/);
    assert.equal(await page.locator('#field-JELLYFIN_HOST_URL').isDisabled(),true);
    assert.equal(await page.locator('form[action="/settings/restore"] button').isEnabled(),true);
    assert.equal(await page.locator('form[action="/settings/apply"]').count(),0);
    assert.deepEqual(errors,[]);
    if(process.env.DASHBOARD_SCREENSHOT_DIRECTORY) {
      await page.setViewportSize({width:1440,height:1000});
      await page.screenshot({path:path.join(process.env.DASHBOARD_SCREENSHOT_DIRECTORY,'settings-recovery.png'),fullPage:true});
      await page.goto('http://fixture.invalid/settings');
      await page.screenshot({path:path.join(process.env.DASHBOARD_SCREENSHOT_DIRECTORY,'settings-ready.png'),fullPage:true});
    }
    console.log(JSON.stringify({status:'settings_workspace_browser_verified',draft_edits_local_only:true,
      ready_stale_clean_review_resubmit_recovery_verified:true,actual_settings_application_performed:false,
      production_services_changed:false}));
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
