import { describe, expect, it } from 'vitest';
import type { DongData, GridProps } from '../types';
import { aggregate, dongCells, mainDong, rankDongs } from './dongs';

const cell = (id: string, extra: Record<string, unknown>) => ({ id, ...extra }) as unknown as GridProps;
const props = new Map<string, GridProps>([
  ['a', cell('a', { electricity_kwh_annual: 1000, electricity_kwh_per_m2: 10, electricity_area_m2: 100, coverage_pct: 20 })],
  ['b', cell('b', { electricity_kwh_annual: 3000, electricity_kwh_per_m2: 30, electricity_area_m2: 300, coverage_pct: 40 })],
  ['c', cell('c', { electricity_kwh_annual: null, electricity_kwh_per_m2: null, electricity_area_m2: null, coverage_pct: null })],
]);
const v = (key: string) => (p: GridProps) => (typeof p[key] === 'number' ? (p[key] as number) : null);

describe('읍면동 aggregation', () => {
  it('sums totals by the share of each cell inside the 행정동 and reports how much of it has values', () => {
    const shares = new Map([['a', 1], ['b', 0.5], ['c', 0.5]]);
    const result = aggregate('electricity_kwh_annual', v('electricity_kwh_annual'), props, shares);
    expect(result.kind).toBe('sum');
    expect(result.value).toBe(2500);
    expect(result.coverage).toBeCloseTo(1.5 / 2);
    expect(result.valuedCells).toBe(2);
  });
  it('weights an intensity by its own denominator (floor area), not by cell count', () => {
    const shares = new Map([['a', 1], ['b', 1]]);
    // (10×100 + 30×300) / 400 = 25, not the plain mean 20.
    expect(aggregate('electricity_kwh_per_m2', v('electricity_kwh_per_m2'), props, shares).value).toBe(25);
    // Shares without a denominator: overlapped-area mean.
    expect(aggregate('coverage_pct', v('coverage_pct'), props, new Map([['a', 1], ['b', 0.5]])).value).toBeCloseTo((20 + 20) / 1.5);
  });
  it('leaves a 행정동 without values empty (never 0)', () => {
    const result = aggregate('electricity_kwh_annual', v('electricity_kwh_annual'), props, new Map([['c', 1]]));
    expect(result.value).toBeNull();
    expect(result.coverage).toBe(0);
  });
});

describe('읍면동 lookups', () => {
  const data = {
    region: '41110', year: 2024, source: '', boundaries: { type: 'FeatureCollection', features: [] },
    dongs: [{ code: '1', name: '가동' }, { code: '2', name: '나동' }, { code: '3', name: '다동' }],
    weights: { a: [[0, 1]], b: [[0, 0.3], [1, 0.7]], c: [[2, 1]] },
  } as unknown as DongData;
  it('lists the cells of one 행정동 and the main 행정동 of a cell', () => {
    expect([...dongCells(data, 0)]).toEqual([['a', 1], ['b', 0.3]]);
    expect(mainDong(data, 'b')).toBe(1);
    expect(mainDong(data, 'zz')).toBeNull();
  });
  it('ranks 행정동 by the metric with the empty ones last', () => {
    const ranks = rankDongs(data, { key: 'electricity_kwh_annual', value: v('electricity_kwh_annual') }, props);
    expect(ranks.map((r) => r.name)).toEqual(['나동', '가동', '다동']);
    expect(ranks[0].result.value).toBe(2100);
    expect(ranks[1].result.value).toBeCloseTo(1900);
    expect(ranks[2].result.value).toBeNull();
  });
});

describe('단지 by 행정동', () => {
  it('counts complex points in the 행정동 that contains them, holes excluded', async () => {
    const { complexesByDong, pointInGeometry } = await import('./dongs');
    const square = (x0: number, y0: number, x1: number, y1: number) => [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]];
    expect(pointInGeometry(0.5, 0.5, { type: 'Polygon', coordinates: [square(0, 0, 1, 1), square(0.4, 0.4, 0.6, 0.6)] })).toBe(false);
    expect(pointInGeometry(0.2, 0.2, { type: 'MultiPolygon', coordinates: [[square(5, 5, 6, 6)], [square(0, 0, 1, 1)]] })).toBe(true);
    const data = {
      region: 'x', year: 2024, source: '', weights: {}, dongs: [{ name: '가' }, { name: '나' }],
      boundaries: { type: 'FeatureCollection', features: [
        { type: 'Feature', properties: { i: 0, code: '1', name: '가' }, geometry: { type: 'Polygon', coordinates: [square(0, 0, 1, 1)] } },
        { type: 'Feature', properties: { i: 1, code: '2', name: '나' }, geometry: { type: 'Polygon', coordinates: [square(1, 0, 2, 1)] } },
      ] },
    } as unknown as DongData;
    const point = (x: number, y: number, households: number | null) => ({ type: 'Feature' as const, properties: { households }, geometry: { type: 'Point' as const, coordinates: [x, y] } });
    const result = complexesByDong(data, { type: 'FeatureCollection', features: [point(0.5, 0.5, 300), point(0.7, 0.2, null), point(1.5, 0.5, 120), point(9, 9, 50)] });
    expect(result).toEqual([{ count: 2, households: 300, withHouseholds: 1 }, { count: 1, households: 120, withHouseholds: 1 }]);
  });
});
