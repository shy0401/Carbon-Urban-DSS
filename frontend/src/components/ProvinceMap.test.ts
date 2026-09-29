import { describe, expect, it } from 'vitest';
import { classify } from '../lib/mapMetrics';
import { DEFAULT_PROVINCE_METRIC_500, groupOf, PROVINCE_GROUPS, PROVINCE_METRICS, rowValue } from '../lib/provinceMetrics';
import type { ProvinceGrid, ProvinceSummary } from '../types';
import { cellId, menuGroups, provinceFeatures } from './ProvinceMap';

const FIELDS = ['x', 'y', 'sgg', 'pop', 'hh', 'housing', 'workers', 'elderly_pct', 'old_housing_pct', 'apartment_pct', 'complexes', 'complex_year', 'region'];
const grid: ProvinceGrid = {
  code: '52', name: '전북특별자치도', kind: 'PROVINCE', sgis_codes: ['35'], fields: FIELDS,
  // x, y are EPSG:5179 lower-left corners ÷ 500.
  cells: [
    [1862, 3493, 0, 1200, 500, 480, 300, 18.5, 40.1, 62.0, 2, 2004, 0],
    [1863, 3493, 0, null, null, null, null, null, null, null, 0, null, -1],
  ],
  sigungu: [{ code: '35011', name: '전주시 완산구', region: '52110' }],
  regions: [{ code: '52110', name: '전북특별자치도 전주시', short_name: '전주시', status: 'READY', grid_count: 916 }],
  boundaries: { type: 'FeatureCollection', features: [] }, bbox: [126.9, 35.7, 127.3, 35.9],
  meta: { cells: 2, sgis_year: 2024, complex_month: '202509', with_stats: 1, no_stat: 1, with_complexes: 1, prepared: 1, grid_source: 'SGIS', stats_source: 'SGIS 1km', complex_source: 'K-apt' },
};

describe('province 500m grid', () => {
  it('draws each row as a closed 500m square and keeps indicators (missing stays null, not 0)', () => {
    const fc = provinceFeatures(grid);
    expect(fc.features).toHaveLength(2);
    const [first, second] = fc.features;
    expect(first.id).toBe(0);
    expect(first.geometry.coordinates[0]).toHaveLength(5);
    expect(first.properties).toMatchObject({ i: 0, pop: 1200, complexes: 2, region: 0 });
    expect(first.properties).not.toHaveProperty('x');
    expect(second.properties?.pop).toBeNull();
    // 931000, 1746500 → about 126.737°E, 35.712°N (PROJ reference in tm5179.test.ts).
    const [lon, lat] = first.geometry.coordinates[0][0];
    expect(lon).toBeCloseTo(126.737, 2);
    expect(lat).toBeCloseTo(35.712, 2);
  });
  it('uses the same cell id as the prepared-region grid (cell_<x>_<y> in metres)', () => {
    expect(cellId(grid, grid.cells[0])).toBe('cell_931000_1746500');
  });
  it('classifies only valued cells and counts missing separately', () => {
    const metric = PROVINCE_METRICS.find((m) => m.key === 'pop')!;
    const c = classify(grid.cells.map((row) => rowValue(grid.fields, row, metric.key)), metric.breaks, metric.ramp);
    expect(c.valued).toBe(1);
    expect(c.missing).toBe(1);
  });
});

describe('SGIS 500m 격자 통계 (자료제공 신청분)', () => {
  const fields = [...FIELDS, 'pop5', 'hh5', 'housing5', 'workers5', 'pop_change5'];
  const rows = [[...grid.cells[0], 310, 120, 110, 45, -12.5], [...grid.cells[1], null, null, null, null, null]];
  it('reads the cells\' own values and leaves cells without a row empty (not 0)', () => {
    expect(rowValue(fields, rows[0], 'pop5')).toBe(310);
    expect(rowValue(fields, rows[1], 'pop5')).toBeNull();
    expect(rowValue(FIELDS, grid.cells[0], 'pop5')).toBeNull(); // older payload without the fields
  });
  it('groups the metrics by source and shows population change on a diverging ramp around 0', () => {
    expect(PROVINCE_GROUPS.map((g) => g.key)).toEqual(['sgis500', 'sgis1k', 'kapt']);
    expect(PROVINCE_METRICS.filter((m) => m.group === 'sgis500').map((m) => m.key)).toEqual(['pop5', 'hh5', 'housing5', 'workers5', 'pop_change5']);
    for (const m of PROVINCE_METRICS) expect(groupOf(m).key).toBe(m.group);
    const change = PROVINCE_METRICS.find((m) => m.key === 'pop_change5')!;
    expect(change.ramp).toBe('diff');
    const c = classify(rows.map((row) => rowValue(fields, row, change.key)), change.breaks, change.ramp);
    expect(c.classes).toHaveLength(5);
    expect(c.missing).toBe(1);
    expect(PROVINCE_METRICS.find((m) => m.key === DEFAULT_PROVINCE_METRIC_500)?.group).toBe('sgis500');
    for (const m of PROVINCE_METRICS.filter((x) => x.group === 'sgis500')) expect(m.definition).toContain('0이 아니라 결측');
  });
});

describe('시·도 menu', () => {
  const p = (code: string, kind: ProvinceSummary['kind'], excluded: string | null = null): ProvinceSummary => ({ code, name: code, kind, sgis_codes: [], cells: 1, regions: 1, prepared: [], excluded });
  it('lists 도 first, then 특별시·광역시, and leaves out excluded ones (제주)', () => {
    const groups = menuGroups([p('11', 'METRO'), p('41', 'PROVINCE'), p('50', 'PROVINCE', '제외'), p('52', 'PROVINCE')]);
    expect(groups.map(([kind]) => kind)).toEqual(['PROVINCE', 'METRO']);
    expect(groups[0][1].map((x) => x.code)).toEqual(['41', '52']);
    expect(groups[1][1].map((x) => x.code)).toEqual(['11']);
  });
  it('drops an empty group', () => {
    expect(menuGroups([p('41', 'PROVINCE')]).map(([kind]) => kind)).toEqual(['PROVINCE']);
  });
});

describe('layer swatch', () => {
  it('shows the metric classes as equal bands (no gradient blending between classes)', async () => {
    const { swatchGradient } = await import('./LayerToggle');
    expect(swatchGradient([])).toBeUndefined();
    expect(swatchGradient(['#111', '#222'])).toBe('linear-gradient(90deg, #111 0.0% 50.0%, #222 50.0% 100.0%)');
  });
});
