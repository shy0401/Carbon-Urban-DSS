import { describe, expect, it } from 'vitest';
import { TOKENS } from '../theme/palette';
import { classIndex, classify, METRIC_GROUPS, METRICS, quantileBounds, rangeLabel, SGIS_GROUP, stepColor, withMetricValues } from './mapMetrics';
import type { GridProps } from '../types';

describe('map classification', () => {
  it('keeps missing values out of the classes and counts them separately', () => {
    const result = classify([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, null, null]);
    expect(result.missing).toBe(2);
    expect(result.valued).toBe(10);
    expect(result.classes.reduce((sum, c) => sum + c.count, 0)).toBe(10);
    expect(result.min).toBe(1);
    expect(result.max).toBe(10);
  });
  it('uses strictly increasing lower bounds above the minimum', () => {
    const bounds = quantileBounds([0, 0, 0, 0, 0, 0, 5, 10, 20, 40]);
    expect(bounds.every((b, i) => b > 0 && (i === 0 || b > bounds[i - 1]))).toBe(true);
  });
  it('places a value equal to a bound in the upper class', () => {
    expect(classIndex(20, [20, 40])).toBe(1);
    expect(classIndex(19.9, [20, 40])).toBe(0);
  });
  it('fixed percentage bounds keep their meaning even when data is narrow', () => {
    const result = classify([12, 15, 18], [20, 40, 60, 80]);
    expect(result.classes[0].count).toBe(3);
    expect(result.classes).toHaveLength(5);
    expect(rangeLabel(result.classes[4], 0, true)).toBe('80 이상');
  });
  it('builds a MapLibre expression with an explicit missing branch (hatch layer on top), not the lowest ramp color', () => {
    const expression = stepColor('coverage_pct', classify([1, 50, 100], [20, 40]));
    expect(expression[0]).toBe('case');
    expect(JSON.stringify(expression)).toContain(TOKENS['prov-missing-bg']);
    expect(JSON.stringify(expression)).toContain('step');
  });
  it('a single valued grid gets a plain color, not a step without stops (MapLibre rejects it)', () => {
    const one = classify([5309649, null, null], undefined, 'load');
    expect(one.lowerBounds).toHaveLength(0);
    const expression = stepColor('electricity_kwh_annual', one);
    expect(JSON.stringify(expression)).not.toContain('step');
    expect(expression[3]).toBe(one.classes[0].color);
  });
  it('uses the load ramp for burdens, gain for benefits and a neutral ramp otherwise', () => {
    expect(classify([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], undefined, 'load').classes.at(-1)?.color).toBe(TOKENS['load-5']);
    expect(classify([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], undefined, 'gain').classes.at(-1)?.color).toBe(TOKENS['gain-5']);
    expect(classify([1, 2, 3, 4, 5, 6, 7, 8, 9, 10]).classes[0].color).toBe(TOKENS['seq-1']);
    const byKey = Object.fromEntries(METRICS.map((m) => [m.key, m.ramp]));
    expect(byKey.electricity_carbon_t).toBe('load');
    expect(byKey.completeness).toBe('gain');
    expect(byKey.far_est_pct).toBe('seq');
  });
  it('derives tCO₂eq from kg and never invents values for missing inputs', () => {
    const props = { electricity_carbon_kg_annual: 2411111.6, completeness: 0, electricity_months: 0, gas_months: 0 } as unknown as GridProps;
    const fc = withMetricValues({ type: 'FeatureCollection', features: [{ type: 'Feature', geometry: { type: 'Point', coordinates: [0, 0] }, properties: props }] });
    const p = fc.features[0].properties as GridProps;
    expect(p.electricity_carbon_t).toBeCloseTo(2411.1116);
    expect(p.completeness).toBeNull();
    expect(p.electricity_kwh_per_m2).toBeNull();
  });
  it('SGIS 1km metrics read the parent cell, stay missing without a statistic and say they are not divided', () => {
    const sgis = METRICS.filter((m) => m.group === SGIS_GROUP);
    expect(METRIC_GROUPS).toContain(SGIS_GROUP);
    expect(sgis.map((m) => m.key)).toEqual(['sgis_pop_density', 'sgis_housing_density', 'sgis_worker_density', 'sgis_elderly_pct', 'sgis_single_household_pct', 'sgis_old_housing_pct', 'sgis_apartment_pct']);
    const pop = sgis[0];
    const observed = { sgis1k_status: 'OBSERVED', sgis1k_code: '다마6862', sgis1k_year: 2024, sgis_pop_density: 13588, sgis1k_households: 5887 } as unknown as GridProps;
    expect(pop.value(observed)).toBe(13588);
    expect(pop.basis(observed)).toContain('1km 격자 다마6862 · 2024년');
    const none = { sgis1k_status: 'NO_STAT', sgis1k_code: '다마0101', sgis1k_year: 2024 } as unknown as GridProps;
    expect(pop.value(none)).toBeNull();
    expect(pop.basis(none)).toBeNull();
    expect(pop.value({} as GridProps)).toBeNull(); // bundle not loaded yet
    for (const metric of sgis) expect(metric.definition).toContain('500m로 나눈 값이 아닙니다');
  });
  it('every metric states its formula and source (근거 유형 배지는 서버 필드가 없어 달지 않음)', () => {
    for (const metric of METRICS) {
      expect(metric.formula.length).toBeGreaterThan(3);
      expect(metric.source.length).toBeGreaterThan(3);
      expect('dataClass' in metric).toBe(false);
    }
  });
});
