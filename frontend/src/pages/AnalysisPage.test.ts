import { describe, expect, it } from 'vitest';
import { adminRows } from './AnalysisPage';
import type { OverlayData } from '../types';

describe('AnalysisPage official context', () => {
  it('행정동 인구를 큰 순서로 정렬하고 비공개 값은 null로 둔다', () => {
    const overlays = { zoning: { type: 'FeatureCollection', features: [] }, admin: { type: 'FeatureCollection', features: [
      { type: 'Feature', geometry: null, properties: { adm_name: '가동', population: 100, population_status: 'OBSERVED' } },
      { type: 'Feature', geometry: null, properties: { adm_name: '나동', population: null, population_status: 'SUPPRESSED' } },
      { type: 'Feature', geometry: null, properties: { adm_name: '다동', population: 300, households: 120, population_density: 5000 } },
    ] }, meta: { zoning_features: 0, admin_features: 3, admin_reference_year: 2023 } } as unknown as OverlayData;
    const rows = adminRows(overlays);
    expect(rows.map((row) => row.name)).toEqual(['다동', '가동', '나동']);
    expect(rows[2].population).toBeNull();
    expect(rows[0].households).toBe(120);
    expect(adminRows(null)).toEqual([]);
  });
});
