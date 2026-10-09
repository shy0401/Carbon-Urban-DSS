import { afterEach, describe, expect, it } from 'vitest';
import { benchmarkPosition, measuresBody, type AreaAnalysis, type Benchmark } from './area';
import { comparisonRows, loadScenarios, MAX_SCENARIOS, SCENARIO_STORE_KEY, scenariosCsv, storeScenarios, toScenario } from './areaScenarios';

const effort = {
  available: true, basis: 'buildings' as const, fallback_from: 'apartments' as const, baseline_year: 2025, baseline_mode: 'OBSERVED' as const, target_pct: 40,
  baseline_kgco2eq: 567049.0, bau_kgco2eq: 1525041.5, target_kgco2eq: 340229.4, required_reduction_kgco2eq: 1184812.1, already_met: false,
  intensity_kwh_per_m2: 44.25, options: { new_only_efficiency_pct: 123.6, all_buildings_efficiency_pct: 77.7, offset_kwh_per_year: 2736287.1, pv_capacity_kw: 2280.6, new_building_intensity_target: null },
  mix: { new_efficiency_pct: 30, existing_efficiency_pct: 10, pv_kw: 100, new_kwh: 663750, existing_kwh: 130958.2, pv_kwh: 120000, pv_counted: true, total_kwh: 914708.2, total_kgco2eq: 396068.7,
    required_kgco2eq: 1184812.1, gap_kgco2eq: 788743.4, met: false, share_pct: 33.4, basis: '식' },
};
const analysis = { history: { area: { label: '완주군 경천면 (행정동)' }, years: [2015, 2025] }, effort } as unknown as AreaAnalysis;
const inputs = { from: 2015, to: 2025, planned_m2: 50000, removed_m2: 0, target_pct: 40, basis: 'apartments' as const, pv_yield: '', measures: { new_efficiency_pct: 30, existing_efficiency_pct: 10, pv_kw: 100 } };

describe('시나리오 비교', () => {
  afterEach(() => window.localStorage.clear());

  it('저장한 안은 엔진 값을 t 단위로 옮기고 표·CSV 행이 같은 순서다', () => {
    const s = toScenario(analysis, { name: '안 A', region: '52710', link: '/area?region=52710&area=admin:35510410', inputs, rank: '3/12번째', now: new Date('2026-10-10T00:00:00Z') });
    expect(s.results).toMatchObject({ basis: 'buildings', fallback_from: 'apartments', need_t: 1184.8121, mix_met: false, rank: '3/12번째' });
    const rows = comparisonRows([s]);
    expect(rows.find((r) => r.label === '기준 건물')?.values[0]).toBe('건물 전체 (건축HUB) (자동 전환)');
    expect(rows.find((r) => r.label === '필요 감축량 (tCO₂eq/년)')?.values[0]).toBe('1,184.8');
    expect(rows.find((r) => r.label === '감축 수단 조합 (tCO₂eq/년)')?.values[0]).toBe('396.1 · 788.7 부족');
    const csv = scenariosCsv([s]);
    expect(csv.startsWith('﻿항목,안 A\r\n구역,완주군 경천면 (행정동)')).toBe(true);
    expect(csv).toContain('"1,184.8"');   // thousands separator quoted for Excel
    expect(csv.split('\r\n').length).toBe(rows.length + 4);
  });

  it('브라우저 저장은 최대 4개, 망가진 값은 빈 목록', () => {
    const s = toScenario(analysis, { name: '안', region: null, link: null, inputs, rank: null });
    expect(storeScenarios([s, s, s, s, s])).toBe(true);
    expect(loadScenarios()).toHaveLength(MAX_SCENARIOS);
    window.localStorage.setItem(SCENARIO_STORE_KEY, '{oops');
    expect(loadScenarios()).toEqual([]);
  });

  it('수단이 모두 0이면 요청에 넣지 않고, 행정동 비교는 같은 연도만 순위를 매긴다', () => {
    expect(measuresBody({ new_efficiency_pct: 0, existing_efficiency_pct: 0, pv_kw: 0 })).toBeNull();
    expect(measuresBody({ new_efficiency_pct: 0, existing_efficiency_pct: 0, pv_kw: 5 })).toEqual({ new_efficiency_pct: 0, existing_efficiency_pct: 0, pv_kw: 5 });
    const bench = { reference_year: 2025, count: 5, quintiles: [30, 40, 50, 60], items: [10, 35, 45, 55, 70].map((v, i) => ({ code: String(i), name: `동${i}`, year: 2025, kwh_per_m2: v, area_m2: 1 }))
      .concat([{ code: 'x', name: '다른 해', year: 2024, kwh_per_m2: 1, area_m2: 1 }]) } as unknown as Benchmark;
    expect(benchmarkPosition(bench, 2025, 44.25)).toEqual({ rank: 3, count: 5, lowerPct: 40, quintile: 3 });
    expect(benchmarkPosition(bench, 2024, 44.25)).toBeNull();
  });
});
