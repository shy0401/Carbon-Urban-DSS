// Browser check for the official data overlays on the map (VWorld zoning, SGIS 행정동 population).
// Overlays that have not been collected yet are reported as SKIP, never as PASS.
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const base = process.env.DSS_URL || 'http://127.0.0.1:5173';
const out = path.resolve(__dirname, '../data/validation');
fs.mkdirSync(out, { recursive: true });
(async () => {
  const browser = await chromium.launch({ headless: true, args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errors = []; const checks = [];
  page.on('pageerror', (error) => errors.push(error.message));
  try {
    const meta = (await (await page.request.get(base + '/api/map/overlays')).json()).meta;
    const mapData = await (await page.request.get(base + '/api/map')).json();
    await page.goto(base + '/map?view=region', { waitUntil: 'domcontentloaded' });
    await page.locator('.maplibregl-canvas').waitFor();
    await page.waitForFunction(() => Number(document.querySelector('.map-canvas')?.dataset.renderedFeatures) > 0, null, { timeout: 60000 });
    // Every map metric shows explicit classes plus a separate "missing (not 0)" row.
    await page.locator('.legend-classes li, .map-empty-hint').first().waitFor();
    checks.push({ name: 'metric_legend_explicit', status: 'PASS', metric: (await page.locator('.metric-trigger strong').innerText()).trim() });
    // Layer switches live in the layer popover.
    await page.getByRole('button', { name: /레이어/ }).first().click();
    for (const [key, label, count, dataKey, legend] of [
      ['zoning', /용도지역 \(VWorld\)/, meta.zoning_features, 'renderedZoning', '용도지역'],
      ['admin', /행정동 인구 \(SGIS\)/, meta.admin_features, 'renderedAdmin', '행정동 인구밀도'],
    ]) {
      const box = page.getByRole('checkbox', { name: label });
      if (!count) {
        // DESIGN.md 2.5: the toggle stays available and, when switched on, says the data is not secured yet.
        await box.check();
        await page.locator('.overlay-missing').filter({ hasText: '자료 미확보' }).first().waitFor();
        await box.uncheck();
        checks.push({ name: key, status: 'SKIP', reason: 'not collected (자료 미확보 notice shown)' });
        continue;
      }
      await box.check();
      await page.waitForFunction((k) => Number(document.querySelector('.map-canvas')?.dataset[k]) > 0, dataKey, { timeout: 60000 });
      await page.getByText(legend, { exact: true }).first().waitFor();
      await page.screenshot({ path: path.join(out, `overlay-${key}.png`), fullPage: true });
      checks.push({ name: key, status: 'PASS', features: count });
      await box.uncheck();
    }
    // Official building footprints (VWorld LT_C_SPBD) are fetched per viewport after zooming in.
    if (mapData.buildings_mode === 'viewport') {
      // Buildings are an overlay (off by default, one overlay at a time).
      await page.getByRole('checkbox', { name: /건물 \(/ }).check();
      await page.getByRole('button', { name: '선택 격자로 확대' }).click();
      await page.waitForFunction(() => Number(document.querySelector('.map-canvas')?.dataset.renderedBuildings) > 0, null, { timeout: 60000 });
      await page.screenshot({ path: path.join(out, 'map-buildings.png'), fullPage: true });
      checks.push({ name: 'official_buildings', status: 'PASS', rendered: await page.evaluate(() => Number(document.querySelector('.map-canvas')?.dataset.renderedBuildings)) });
    } else {
      checks.push({ name: 'official_buildings', status: 'SKIP', reason: 'VWorld buildings not collected (OSM fallback shown)' });
    }
    // Analysis screen: official-data charts render only when the data exists.
    await page.goto(base + '/analysis', { waitUntil: 'domcontentloaded' });
    await page.getByText('행정동 인구', { exact: true }).first().waitFor();
    for (const [name, count, label] of [
      ['analysis_population_chart', meta.admin_features, 'SGIS 행정동별 인구 막대 차트'],
      ['analysis_zoning_chart', meta.zoning_features, '분석 격자 내 용도지역 면적 구성 차트'],
    ]) {
      if (!count) { checks.push({ name, status: 'SKIP', reason: 'not collected' }); continue; }
      const chart = page.getByRole('img', { name: label });
      await chart.waitFor();
      await page.waitForFunction((l) => !!document.querySelector(`[aria-label="${l}"] canvas`), label, { timeout: 30000 });
      checks.push({ name, status: 'PASS' });
    }
    await page.screenshot({ path: path.join(out, 'analysis-official.png'), fullPage: true });
    // Report: official context section is generated from DB values (no AI numbers).
    const created = await page.request.post(base + '/api/reports', { data: { year: 2025 } });
    if (created.status() !== 201) throw new Error('report creation failed: ' + created.status());
    const report = await created.json();
    const contextFacts = (report.context && report.context.facts) || [];
    if (!contextFacts.length) throw new Error('report has no official context facts');
    const markdown = await (await page.request.get(base + `/api/reports/${report.id}/markdown`)).text();
    if (!markdown.includes('대상지 공식 현황')) throw new Error('markdown export lacks the official context section');
    checks.push({ name: 'report_official_context', status: 'PASS', facts: contextFacts.map((fact) => fact.id) });
    if (errors.length) throw new Error('page errors: ' + errors.join(' | '));
    fs.writeFileSync(path.join(out, 'overlays.json'), JSON.stringify({ checks, meta, pageErrors: errors }, null, 2));
    console.log(JSON.stringify({ overlays: checks.map((c) => `${c.name}:${c.status}`), passed: checks.filter((c) => c.status === 'PASS').length }));
  } finally {
    await browser.close();
  }
})().catch((error) => { console.error(error.message); process.exitCode = 1; });
