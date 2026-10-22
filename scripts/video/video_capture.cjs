// 사용 영상 화면 촬영(이 PC). capture.json의 줄마다 동작 → 화면(1920×1080) + 강조 상자 좌표.
// 국토통계지도·선도소프트 100m·팀 변화 모델 패널과 그 레이어 줄은 숨긴다. 숨김이 실패해 보이면 그 줄은 저장하지 않는다.
// 계획안·보고서를 만든 줄은 그 id를 created-video.json에 남겨 촬영 뒤 지운다(cleanup_shots2.py).
const { chromium } = require('playwright');
const fs = require('fs');
const base = process.env.DSS_URL || 'http://frontend';
const dir = process.env.SHOT_DIR || '/work/data/ops/claude-runner/shots/video';
const plan = JSON.parse(fs.readFileSync(process.env.PLAN || '/work/data/ops/claude-runner/capture.json', 'utf8'));
const only = (process.env.ONLY || '').split(',').filter(Boolean);
fs.mkdirSync(dir, { recursive: true });
const HIDE = '.grid100-panel,[data-testid="team-model-panel"],[data-testid="area-kcsm"],[data-testid="kcsm-basis-note"],[data-testid="kcsm100-panel"]';
const W = 1920, H = 1080;
const out = { lines: {}, errors: [], created: [] };

const short = (e) => String(e && e.message || e).split('\n')[0].replace(/https?:\/\/\S+/g, '<url>').slice(0, 200);
async function hide(p) {
  await p.addStyleTag({ content: `${HIDE}{display:none!important} .skip-link{display:none!important}` }).catch(() => {});
  await p.evaluate(() => {
    for (const el of document.querySelectorAll('label.layer-toggle, .overlay-legend, .legend-row, li')) {
      if (/국토통계지도|탄소공간지도|100m 전기|100m 격자/.test(el.textContent || '') && el.closest('.map-tools, .map-rail, .layer-panel, .map-layers, .overlay-legend, label')) el.style.display = 'none';
    }
  }).catch(() => {});
}
async function restrictedVisible(p) {
  return p.evaluate((sel) => [...document.querySelectorAll(sel)].some((el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0 && getComputedStyle(el).display !== 'none'; }), HIDE);
}
async function box(p, sel) {
  if (!sel) return null;
  for (const s of sel.split(/,(?![^()]*\))(?![^\[]*\])/).map((x) => x.trim()).filter(Boolean)) {
    try {
      const loc = p.locator(s).first();
      if (!(await loc.count())) continue;
      const b = await loc.boundingBox();
      if (!b || b.width < 4 || b.height < 4) continue;
      const x = Math.max(0, b.x), y = Math.max(0, b.y);
      const w = Math.min(W, b.x + b.width) - x, h = Math.min(H, b.y + b.height) - y;
      if (w > 4 && h > 4) return [Math.round(x), Math.round(y), Math.round(w), Math.round(h)];
    } catch { /* try the next selector */ }
  }
  return null;
}
async function center(p, sel) {
  for (const s of sel.split(/,(?![^()]*\))(?![^\[]*\])/).map((x) => x.trim()).filter(Boolean)) {
    const loc = p.locator(s).first();
    if (await loc.count()) { await loc.evaluate((el) => el.scrollIntoView({ block: 'center', inline: 'nearest' })).catch(() => {}); return true; }
  }
  return false;
}
async function mapReady(p) {
  await p.waitForSelector('.map-canvas', { timeout: 240000 });
  await p.waitForFunction(() => Number(document.querySelector('.map-canvas')?.dataset.renderedFeatures) > 0, null, { timeout: 240000 });
}
async function setScope(p, scope) {
  await p.evaluate((s) => { localStorage.setItem('carbon-analysis-scope', JSON.stringify(s)); localStorage.removeItem('carbon-map-view'); }, scope);
}
async function shot(p, name) {
  await hide(p);
  await p.waitForTimeout(700);
  if (await restrictedVisible(p)) return false;
  await p.screenshot({ path: `${dir}/${name}.jpg`, type: 'jpeg', quality: 90 });
  return true;
}

(async () => {
  const b = await chromium.launch({ headless: true, args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'] });
  const ctx = await b.newContext({ viewport: { width: W, height: H }, locale: 'ko-KR', timezoneId: 'Asia/Seoul' });
  const p = await ctx.newPage();
  p.on('pageerror', (e) => out.errors.push('pageerror ' + short(e)));
  p.on('response', async (r) => {
    try {
      const u = new URL(r.url());
      if (r.request().method() === 'POST' && /^\/api\/(scenarios|reports)\/?$/.test(u.pathname) && r.ok()) {
        const j = await r.json(); if (j && j.id) out.created.push({ id: j.id, path: u.pathname });
      }
    } catch { /* ignore */ }
  });
  await p.goto(base + '/guide', { waitUntil: 'domcontentloaded', timeout: 120000 });
  await p.evaluate(() => localStorage.clear());
  for (const item of plan) {
    if (only.length && !only.includes(item.id)) continue;
    const rec = { focus: null, click: null, pre: false, saved: false };
    try {
      if (item.url) {
        if (item.scope) await setScope(p, item.scope);
        await p.goto(base + item.url, { waitUntil: 'domcontentloaded', timeout: 120000 });
        await p.waitForLoadState('networkidle', { timeout: 30000 }).catch(() => {});
      }
      let preTaken = false;
      for (const a of item.actions || []) {
        const kind = Object.keys(a)[0];
        const v = a[kind];
        if ((kind === 'click') && item.pre && !preTaken) {
          await center(p, v);
          await p.waitForTimeout(500);
          rec.click = await box(p, v);
          rec.pre = await shot(p, `${item.id}_pre`);
          preTaken = true;
        }
        if (kind === 'wait') await p.waitForTimeout(v);
        else if (kind === 'waitFor') await p.waitForSelector(v, { state: 'visible', timeout: 420000 });
        else if (kind === 'click') { const loc = p.locator(v).first(); await loc.scrollIntoViewIfNeeded().catch(() => {}); await loc.click({ timeout: 30000 }); }
        else if (kind === 'fill') { const loc = p.locator(v[0]).first(); await loc.fill(String(v[1])); await loc.press('Tab').catch(() => {}); }
        else if (kind === 'press') await p.keyboard.press(v[1]);
        else if (kind === 'mapReady') await mapReady(p);
        else if (kind === 'scrollTo') await center(p, v);
        else if (kind === 'selectGrid') {
          await setScope(p, { year: 2025, gridId: v, region: null });
          await p.reload({ waitUntil: 'domcontentloaded' });
          await mapReady(p); await p.waitForTimeout(2500);
          if (await p.locator('.detail-tab').count()) await p.locator('.detail-tab').first().click();
        } else if (kind === 'eval') await p.evaluate(v);
      }
      if (item.scroll) await center(p, item.scroll);
      if (item.scrollY !== undefined) await p.evaluate((y) => window.scrollTo(0, y), item.scrollY);
      await p.waitForTimeout(900);
      rec.saved = await shot(p, item.id);
      rec.focus = await box(p, item.focus);
      if (!rec.saved) rec.skipped = 'restricted_visible';
    } catch (e) { rec.error = short(e); out.errors.push(`${item.id}: ${rec.error}`); try { rec.saved = await shot(p, item.id); rec.focus = await box(p, item.focus); } catch { /* keep going */ } }
    out.lines[item.id] = rec;
    console.log(item.id, JSON.stringify(rec));
  }
  await b.close();
  fs.writeFileSync(`${dir}/boxes.json`, JSON.stringify(out, null, 1));
  fs.writeFileSync(`${dir}/created-video.json`, JSON.stringify(out.created, null, 1));
  console.log('errors', JSON.stringify(out.errors), 'created', out.created.length);
})();
