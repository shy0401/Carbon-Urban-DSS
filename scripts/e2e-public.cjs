const {chromium} = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const base = fs.readFileSync('data/deployment/public-url.txt', 'utf8').trim();
const credentials = JSON.parse(fs.readFileSync('.secrets/prototype-credentials.json', 'utf8').replace(/^\uFEFF/, ''));
const out = path.resolve('data/deployment');

(async () => {
  const browser = await chromium.launch({headless:true,args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  const context = await browser.newContext({viewport:{width:1440,height:1050},httpCredentials:{...credentials,origin:base}});
  const page = await context.newPage();
  page.setDefaultTimeout(60000);
  const errors = [], checks = [];
  page.on('pageerror', e => errors.push(e.message));
  try {
    const health = await context.request.get(base+'/api/health');
    assert.equal(health.status(),200);
    assert.equal((await health.json()).database,'connected'); checks.push('public_postgis_connected');
    assert.equal((await (await context.request.get(base+'/api/system')).json()).offline_mode,false); checks.push('online_collection_enabled');
    await page.goto(base); await page.locator('.metric-card').first().waitFor();
    assert.equal(await page.locator('.metric-card').count(),8); checks.push('public_dashboard');
    await page.goto(base+'/map');
    await page.waitForFunction(()=>Number(document.querySelector('.map-canvas')?.dataset.renderedFeatures)>0);
    await page.screenshot({path:path.join(out,'public-map.png'),fullPage:true}); checks.push('public_real_map');
    await page.goto(base+'/simulation'); await page.getByRole('button',{name:'30층',exact:true}).click();
    const [scenario] = await Promise.all([page.waitForResponse(r=>r.url().endsWith('/api/scenarios')&&r.request().method()==='POST'),page.getByRole('button',{name:'시나리오 계산',exact:true}).click()]);
    assert.equal(scenario.status(),200); checks.push('public_scenario_saved');
    await page.getByRole('link',{name:'이 계획안으로 보고서 작성'}).click();
    await page.getByRole('button',{name:'보고서 작성',exact:true}).click();
    await page.locator('.report-paper').waitFor(); checks.push('public_report_saved');
    const [download] = await Promise.all([page.waitForEvent('download'),page.getByRole('link',{name:'문서 내려받기'}).click()]);
    await download.saveAs(path.join(out,'public-report.md')); assert(fs.readFileSync(path.join(out,'public-report.md'),'utf8').includes('근거 SHA256')); checks.push('public_report_download');
    await page.screenshot({path:path.join(out,'public-report.png'),fullPage:true});
    const ai = await context.request.post(base+'/api/reports',{data:{year:2025,use_local_model:true},timeout:120000});
    assert.equal(ai.status(),201); assert.equal((await ai.json()).summary.mode,'LOCAL_SLM'); checks.push('public_local_ai');
    const collection = await context.request.post(base+'/api/collections',{data:{datasets:['weather'],start_month:'2025-01',end_month:'2025-12'}});
    assert(collection.ok()); const job = await collection.json();
    let completed;
    for(let attempt=0;attempt<30;attempt++) {
      const jobs=await (await context.request.get(base+'/api/collections')).json();
      completed=jobs.find(row=>row.id===job.id);
      if(completed&&!['PENDING','QUEUED','RUNNING','STARTED'].includes(completed.status)) break;
      await new Promise(resolve=>setTimeout(resolve,1000));
    }
    assert.equal(completed?.status,'COMPLETED'); checks.push('public_collection_worker_completed');
    await page.setViewportSize({width:390,height:844}); await page.goto(base+'/reports'); await page.locator('.page-header').waitFor();
    assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1)); checks.push('public_mobile');
    assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(out,'checks.json'),JSON.stringify({url:base,checked_at:new Date().toISOString(),checks,pageErrors:errors,collection:{id:job.id,status:completed.status}},null,2));
    console.log(JSON.stringify({passed:checks.length,pageErrors:errors,collection:completed.status}));
  } catch(error) {await page.screenshot({path:path.join(out,'failure.png'),fullPage:true});throw error;}
  finally {await browser.close();}
})().catch(error=>{console.error(error.message);process.exitCode=1;});
