import { describe, expect, it } from 'vitest';
import { adminRows, shortAdminName } from './AnalysisPage';
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
  it('행정동 이름에서 시도·시 접두어를 줄여 표시한다', () => {
    expect(shortAdminName('전북특별자치도 전주시 덕진구 송천1동')).toBe('덕진구 송천1동');
    expect(shortAdminName('효자4동')).toBe('효자4동');
  });
});

describe('shortAdminName outside Jeonju', () => {
  it('keeps the district and the dong of any region', () => {
    expect(shortAdminName('경기도 수원시 장안구 파장동')).toBe('장안구 파장동');
    expect(shortAdminName('서울특별시 종로구 청운효자동')).toBe('종로구 청운효자동');
    expect(shortAdminName('세종특별자치시 조치원읍')).toBe('세종특별자치시 조치원읍');
  });
});
