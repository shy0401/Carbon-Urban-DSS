import { describe, expect, it } from 'vitest';
import { TOKENS } from '../theme/palette';
import { isBasemapError, metricColor, selectedFilter } from './MapPage';

describe('MapPage expressions', () => {
  it('배경 타일 오류를 분석 도형 오류와 구분한다', () => {
    expect(isBasemapError({sourceId:'basemap',error:{message:'HTTP 403'}})).toBe(true);
    expect(isBasemapError({error:{message:'https://tile.openstreetmap.org/12/1/2.png 403'}})).toBe(true);
    expect(isBasemapError({sourceId:'grids',error:{message:'Invalid geometry'}})).toBe(false);
  });
  it('선정 섹터를 id 또는 grid_id 속성으로 강조한다', () => {
    expect(JSON.stringify(selectedFilter('g-1'))).toContain('coalesce');
    expect(JSON.stringify(selectedFilter('g-1'))).toContain('id');
    expect(JSON.stringify(selectedFilter('g-1'))).toContain('grid_id');
  });

  it('결측 지도값에 명시적인 결측 분기를 둔다(램프 최저색이 아님)', () => {
    expect(metricColor('carbon_kg')[0]).toBe('case');
    expect(JSON.stringify(metricColor('carbon_kg'))).toContain(TOKENS['prov-missing-bg']);
    expect(JSON.stringify((metricColor('carbon_kg') as unknown[])[3])).not.toContain(TOKENS['prov-missing-bg']);
  });
});

describe('MapPage overlays', () => {
  it('용도지역 범주별 색과 미분류 기본색을 가진다', async () => {
    const { zoneColor, ZONE_LEGEND } = await import('./MapPage');
    const expression = JSON.stringify(zoneColor());
    expect(expression).toContain('RESIDENTIAL');
    expect(expression).toContain(ZONE_LEGEND[4][2]);
  });
  it('용도지역 외곽선은 세부 명칭별 토큰 색을 쓴다', async () => {
    const { zoneLineColor } = await import('./MapPage');
    const expression = JSON.stringify(zoneLineColor());
    expect(expression).toContain('제2종일반주거');
    expect(expression).toContain(TOKENS['zone-r2']);
    expect(expression).toContain(TOKENS['zone-gc']);
  });
  it('행정동 인구밀도 결측은 회색으로 두고 최대값으로 색 범위를 정한다', async () => {
    const { densityColor, maxOf } = await import('./MapPage');
    expect(JSON.stringify(densityColor(1000))).toContain(TOKENS['prov-missing-bg']);
    expect(JSON.stringify(densityColor(1000))).toContain(TOKENS['seq-5']);
    const fc = { type: 'FeatureCollection', features: [{ type: 'Feature', geometry: null, properties: { population_density: 12 } }, { type: 'Feature', geometry: null, properties: { population_density: null } }] } as unknown as GeoJSON.FeatureCollection;
    expect(maxOf(fc, 'population_density')).toBe(12);
    expect(maxOf(undefined, 'population_density')).toBe(0);
  });
  it('비공개·미수집 통계를 0으로 표시하지 않는다', async () => {
    const { statValue } = await import('./MapPage');
    expect(statValue(null, 'SUPPRESSED', '명')).toBe('비공개(*)');
    expect(statValue(undefined, 'NOT_COLLECTED', '명')).toBe('미수집');
    expect(statValue(null, 'NOT_AVAILABLE', '명')).toBe('자료 없음');
    expect(statValue(0, 'OBSERVED_ZERO', '명')).toContain('0');
  });
});

describe('MapPage views and layers', () => {
  it('opens the 시·도 of the address, then the remembered one, then the analysis region (never 제주)', async () => {
    const { pickProvince } = await import('./MapPage');
    expect(pickProvince('41', '52', '52110')).toBe('41');
    expect(pickProvince(null, '11', '52110')).toBe('11');
    expect(pickProvince(null, null, '52110')).toBe('52');
    expect(pickProvince('50', null, '41111')).toBe('41');
    expect(pickProvince('x', 'bad', null)).toBe('52');
  });
  it('keeps one overlay at a time and leaves the grid and boundary alone', async () => {
    const { toggleLayer } = await import('./MapPage');
    const base = { grids: true, buildings: false, complexes: false, boundary: true, zoning: true, admin: false };
    const next = toggleLayer(base, 'admin', true);
    expect(next).toEqual({ grids: true, buildings: false, complexes: false, boundary: true, zoning: false, admin: true });
    expect(toggleLayer(next, 'boundary', false)).toMatchObject({ admin: true, boundary: false });
    expect(toggleLayer(next, 'admin', false)).toMatchObject({ admin: false, zoning: false, grids: true });
  });
  it('fades the grid colour while an overlay is shown', async () => {
    const { gridOpacity } = await import('./MapPage');
    expect(JSON.stringify(gridOpacity(true))).toContain('0.3');
    expect(JSON.stringify(gridOpacity(false))).toContain('0.85');
  });
});

describe('읍면동 labels', () => {
  it('names the 행정동 a cell lies in, largest part first', async () => {
    const { dongLabel } = await import('./MapPage');
    const data = { dongs: [{ name: '효자1동' }, { name: '효자2동' }], weights: { a: [[0, 0.3], [1, 0.7]], b: [[0, 1]] } } as never;
    expect(dongLabel(data, 'a')).toBe('효자2동 · 효자1동');
    expect(dongLabel(data, 'a', true)).toBe('행정동: 효자2동 70%, 효자1동 30%');
    expect(dongLabel(data, 'zz')).toBeNull();
    expect(dongLabel(null, 'a')).toBeNull();
  });
});
