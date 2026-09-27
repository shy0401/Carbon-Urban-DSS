import { describe, expect, it } from 'vitest';
import { regionRows, statusTone } from './RegionsPage';
import { regionParam, setAnalysisScope } from '../hooks/useAnalysisScope';
import type { NationalOverview, NationalRegionProps } from '../types';

const region = (code: string, name: string, sido: string, density: number | null): { type: 'Feature'; geometry: null; properties: NationalRegionProps } => ({
  type: 'Feature', geometry: null,
  properties: { code, name, sido_name: sido, districts: [], population: density, households: null, density, area_km2: null, complexes: 0, study_status: 'NOT_PREPARED', sgis_codes: [] },
});

describe('RegionsPage table', () => {
  const overview: NationalOverview = { type: 'FeatureCollection', meta: { year: 2024, regions: 3 }, features: [
    region('41110', '경기도 수원시', '경기도', 9900), region('52110', '전북특별자치도 전주시', '전북특별자치도', 3200), region('41820', '경기도 가평군', '경기도', null),
  ] };
  it('sorts by the metric with missing values last and filters by name and province', () => {
    expect(regionRows(overview, '', '', 'density').map((r) => r.code)).toEqual(['41110', '52110', '41820']);
    expect(regionRows(overview, '전 주', '', 'density').map((r) => r.code)).toEqual(['52110']);
    expect(regionRows(overview, '', '경기도', 'density').map((r) => r.code)).toEqual(['41110', '41820']);
  });
  it('maps states to tones', () => {
    expect(statusTone('READY')).toBe('good');
    expect(statusTone('WAITING')).toBe('warn');
    expect(statusTone('FAILED')).toBe('bad');
    expect(statusTone('PREPARING')).toBe('neutral');
  });
});

describe('analysis scope region', () => {
  it('adds the region to queries and clears the grid when the region changes', () => {
    expect(regionParam(null)).toBe('');
    expect(regionParam('41110')).toBe('&region=41110');
    expect(regionParam('41110', '?')).toBe('?region=41110');
    setAnalysisScope({ region: null, gridId: 'cell_1_1' });
    setAnalysisScope({ region: '41110' });
    const saved = JSON.parse(localStorage.getItem('carbon-analysis-scope') || '{}');
    expect(saved.region).toBe('41110');
    expect(saved.gridId).toBeNull();
    setAnalysisScope({ region: null });
  });
});
