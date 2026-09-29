import { describe, expect, it } from 'vitest';
import type { NationalData, NationalRegion } from '../types';
import { bboxOf, provinceFeatures, rankRegions } from './NationalMap';

const square = (x: number, y: number): GeoJSON.Polygon => ({ type: 'Polygon', coordinates: [[[x, y], [x + 1, y], [x + 1, y + 1], [x, y + 1], [x, y]]] });
const metrics = (population: number | null) => ({ population, households: null, area_km2: null, density: null, pop500: null, pop500_base: null, pop_change_pct: null, housing500: null, workers500: null, complexes: null });

describe('national map helpers', () => {
  it('computes bounds of (multi)polygons and returns null without coordinates', () => {
    expect(bboxOf([{ type: 'Feature', geometry: square(126, 35), properties: {} }, { type: 'Feature', geometry: square(128, 37), properties: {} }])).toEqual([126, 35, 129, 38]);
    expect(bboxOf([])).toBeNull();
  });
  it('puts the chosen metric of each 시·도 on its boundary (missing stays null)', () => {
    const data = {
      provinces: [{ code: '52', metrics: metrics(1700000) }, { code: '50', metrics: metrics(null) }],
      boundaries: { type: 'FeatureCollection', features: [{ type: 'Feature', geometry: square(126, 35), properties: { code: '52' } }, { type: 'Feature', geometry: square(126, 33), properties: { code: '50' } }] },
    } as unknown as NationalData;
    const fc = provinceFeatures(data, 'population');
    expect(fc.features.map((f) => f.properties?.v)).toEqual([1700000, null]);
    expect(provinceFeatures(null, 'population').features).toHaveLength(0);
  });
  it('ranks the 시·군·구 of one 시·도 with empty values last, never as 0', () => {
    const r = (code: string, sido: string, population: number | null, short_name: string) => ({ code, sido, short_name, metrics: metrics(population) }) as unknown as NationalRegion;
    const ranked = rankRegions([r('52110', '52', 640000, '전주시'), r('52710', '52', null, '완주군'), r('52130', '52', 270000, '군산시'), r('41110', '41', 1190000, '수원시')], '52', 'population');
    expect(ranked.map((x) => x.short_name)).toEqual(['전주시', '군산시', '완주군']);
  });
});
