const {chromium}=require('playwright');
const fs=require('node:fs');
const assert=require('node:assert/strict');
(async()=>{
 const base=fs.readFileSync('data/deployment/public-url.txt','utf8').trim();
 const c=JSON.parse(fs.readFileSync('.secrets/prototype-credentials.json','utf8').replace(/^\uFEFF/,''));
 const browser=await chromium.launch({headless:true,args:['--use-gl=angle','--use-angle=swiftshader','--enable-unsafe-swiftshader']});
 const context=await browser.newContext({viewport:{width:1440,height:1100},httpCredentials:{...c,origin:base}});
 const page=await context.newPage();page.setDefaultTimeout(45000);
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 try{
  // One stationary viewport only: no scans or tile prefetching.
  const tiles=[];page.on('response',r=>{if(r.url().startsWith('https://tile.openstreetmap.org/'))tiles.push(r)});
  const response=await page.goto(base+'/map');
  assert.equal(response.headers()['referrer-policy'],'strict-origin-when-cross-origin');
  await page.waitForFunction(()=>Number(document.querySelector('.map-canvas')?.dataset.renderedFeatures)>0);
  await page.waitForTimeout(2000);
  assert(tiles.some(r=>r.status()===200),'No successful background tiles');
  assert(tiles.every(r=>r.status()!==403),'Background tiles still return 403');
  const tileHeaders=await tiles[0].request().allHeaders();
  assert.equal(tileHeaders.referer,base+'/');
  await page.screenshot({path:'data/deployment/map-fixed.png',fullPage:true});
  // Fault injection replaces tile traffic; all interaction below uses mocked 403 responses.
  await page.route('https://tile.openstreetmap.org/**',r=>r.fulfill({status:403,body:'blocked'}));
  await page.reload();await page.getByRole('status').filter({hasText:'배경지도 연결 실패'}).waitFor();
  await page.waitForFunction(()=>Number(document.querySelector('.map-canvas')?.dataset.renderedFeatures)>0);
  await page.getByRole('button',{name:'선택 격자로 확대'}).click();
  await page.locator('.maplibregl-canvas').click({position:{x:430,y:280}});
  await page.getByRole('link',{name:'이 격자 시뮬레이션'}).waitFor();
  await page.screenshot({path:'data/deployment/map-fallback.png',fullPage:true});
  await page.setViewportSize({width:390,height:844});
  assert(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1));
  assert.deepEqual(errors,[]);
  fs.writeFileSync('data/deployment/map-check.json',JSON.stringify({referrer:tileHeaders.referer,tileResponses:tiles.length,realTiles:'200',fallback:'passed',selection:'passed',mobile:'passed',pageErrors:errors},null,2));
  console.log('Public map: referrer, real tiles, fault fallback, selection, mobile passed');
 }finally{await browser.close();}
})().catch(e=>{console.error(e.message);process.exitCode=1});
