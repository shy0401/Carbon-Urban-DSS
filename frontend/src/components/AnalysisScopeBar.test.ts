import { describe, expect, it } from 'vitest';
import { groupRegions, provinceOptions } from './AnalysisScopeBar';

describe('analysis region selector', () => {
  it('lists regions with their own detail data first and national-only maps apart', () => {
    const groups = groupRegions([
      { code: '41820', short_name: '가평군', name: '경기도 가평군', level: 'BASIC' },
      { code: '52110', short_name: '전주시', name: '전북특별자치도 전주시', level: 'DETAILED' },
      { code: '41110', short_name: '수원시', name: '경기도 수원시', level: 'DETAILED' },
    ]);
    expect(groups.map(([label, items]) => [label, items.map((i) => i.short_name)])).toEqual([
      ['상세 자료', ['수원시', '전주시']], ['기본 지도 (전국 공통 자료)', ['가평군']],
    ]);
  });
  it('adds regions without a map yet as their own group (opened in seconds when picked)', () => {
    const groups = groupRegions([{ code: '52710', short_name: '완주군', name: '전북특별자치도 완주군', level: 'BASIC' }, { code: '52130', short_name: '군산시', name: '전북특별자치도 군산시', level: 'NONE' }]);
    expect(groups.map(([label, items]) => [label, items.length])).toEqual([['상세 자료', 0], ['기본 지도 (전국 공통 자료)', 1], ['지도 없음 (처음 열면 몇 초)', 1]]);
  });
  it('lists 시·도 once each, 도 first', () => {
    const out = provinceOptions([{ code: '52110', sido_name: '전북특별자치도' }, { code: '11110', sido_name: '서울특별시' }, { code: '52710', sido_name: '전북특별자치도' }, { code: '41110', sido_name: '경기도' }, { code: '12110', sido_name: '전남광주통합특별시' }]);
    expect(out.map((p) => [p.code, p.kind])).toEqual([['12', 'PROVINCE'], ['41', 'PROVINCE'], ['52', 'PROVINCE'], ['11', 'METRO']]);
  });
});
