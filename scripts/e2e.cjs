const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const base = process.env.DSS_URL || 'http://127.0.0.1:5173';
const out = path.resolve(__dirname, '../data/validation');
fs.mkdirSync(out,{recursive:true});
(async()=>{
  const browser=await chromium.launch({headless:true,args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
  const context=await browser.newContext({viewport:{width:1440,height:1000}});
  const page=await context.newPage(); const errors=[]; const checks=[];
  page.on('pageerror',e=>errors.push(e.message));
  try {
    for(const [route,expected] of [['/','Carbon Urban'],['/data','수집 데이터'],['/data/sources/weather','기상'],['/map','도시 탄소 지도'],['/model','모델'],['/simulation','시뮬레이션']]){
      const response=await page.goto(base+route,{waitUntil:'domcontentloaded'});
      assert.equal(response.status(),200);
      await page.getByText(expected,{exact:false}).first().waitFor();
      assert(!/Internal Server Error/.test(await page.locator('body').innerText()));
      await page.screenshot({path:path.join(out,(route.replaceAll('/','_')||'dashboard')+'.png'),fullPage:true});
      checks.push({route,status:'PASS'});
    }
    await page.getByRole('button',{name:'30층',exact:true}).click();
    await page.getByRole('button',{name:'시나리오 계산',exact:true}).click();
    await page.getByText('기준 자료가 없어 추정할 수 없습니다',{exact:false}).or(page.getByText('해석 범위',{exact:true})).first().waitFor();
    checks.push({name:'scenario30_floor_calculation',status:'PASS'});
    const [optimized]=await Promise.all([page.waitForResponse(r=>r.url().endsWith('/api/optimize')),page.getByRole('button',{name:'최적안 탐색',exact:true}).click()]);
    assert.equal(optimized.status(),200);
    checks.push({name:'optimization_request',status:'PASS'});
    const original=await (await context.request.get(base+'/api/system')).json();
    await context.request.post(base+'/api/system/offline',{data:{enabled:true}});
    const denied=await context.request.post(base+'/api/collections',{data:{datasets:['weather'],start_month:'2025-01',end_month:'2025-12'}});
    assert.equal(denied.status(),409);
    const external=[];
    await context.route('**/*',route=>{
      if(!route.request().url().startsWith(base)){external.push(route.request().url());return route.abort();}
      return route.continue();
    });
    await page.goto(base+'/map',{waitUntil:'domcontentloaded'});
    await page.locator('.maplibregl-canvas').waitFor();
    await page.waitForFunction(()=>Number(document.querySelector('.map-canvas')?.dataset.renderedFeatures)>0);
    assert.equal(external.length,0,'offline map attempted external resources: '+external.join(', '));
    await page.screenshot({path:path.join(out,'offline-map.png'),fullPage:true});
    checks.push({name:'offline_map_renders_real_features_without_external_requests',status:'PASS'});
    await context.request.post(base+'/api/system/offline',{data:{enabled:original.offline_mode}});
    assert.deepEqual(errors,[]);
    fs.writeFileSync(path.join(out,'e2e.json'),JSON.stringify({checks,pageErrors:errors},null,2));
    console.log(JSON.stringify({passed:checks.length,pageErrors:errors}));
  } finally {await browser.close();}
})().catch(e=>{console.error(e.message);process.exitCode=1});
