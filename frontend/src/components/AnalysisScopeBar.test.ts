import { describe, expect, it } from 'vitest';
import { groupRegions } from './AnalysisScopeBar';

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
});
