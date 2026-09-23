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
    await page.goto(base + '/map', { waitUntil: 'domcontentloaded' });
    await page.locator('.maplibregl-canvas').waitFor();
    await page.waitForFunction(() => Number(document.querySelector('.map-canvas')?.dataset.renderedFeatures) > 0, null, { timeout: 60000 });
    for (const [key, label, count, dataKey, legend] of [
      ['zoning', /용도지역 \(VWorld\)/, meta.zoning_features, 'renderedZoning', '용도지역'],
      ['admin', /행정동 인구 \(SGIS\)/, meta.admin_features, 'renderedAdmin', '행정동 인구밀도'],
    ]) {
      const box = page.getByRole('checkbox', { name: label });
      if (!count) {
        if (!(await box.isDisabled())) throw new Error(`${key}: empty overlay must be disabled`);
        checks.push({ name: key, status: 'SKIP', reason: 'not collected' });
        continue;
      }
      await box.check();
      await page.waitForFunction((k) => Number(document.querySelector('.map-canvas')?.dataset[k]) > 0, dataKey, { timeout: 60000 });
      await page.getByText(legend, { exact: true }).first().waitFor();
      await page.screenshot({ path: path.join(out, `overlay-${key}.png`), fullPage: true });
      checks.push({ name: key, status: 'PASS', features: count });
      await box.uncheck();
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
    if (errors.length) throw new Error('page errors: ' + errors.join(' | '));
    fs.writeFileSync(path.join(out, 'overlays.json'), JSON.stringify({ checks, meta, pageErrors: errors }, null, 2));
    console.log(JSON.stringify({ overlays: checks.map((c) => `${c.name}:${c.status}`), passed: checks.filter((c) => c.status === 'PASS').length }));
  } finally {
    await browser.close();
  }
})().catch((error) => { console.error(error.message); process.exitCode = 1; });
