import { describe, expect, it } from 'vitest';
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

  it('결측 지도값에 명시적인 회색 분기를 둔다', () => {
    expect(metricColor('carbon_kg')[0]).toBe('case');
    expect(JSON.stringify(metricColor('carbon_kg'))).toContain('#cbd5d1');
  });
});
