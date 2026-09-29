import { describe, expect, it } from 'vitest';
import { levelLabel, metricValue, missingReason, NATIONAL_METRICS, provinceGroups, shortProvince } from './nationalMetrics';
import { withTopic } from './format';

describe('national metrics', () => {
  const byKey = Object.fromEntries(NATIONAL_METRICS.map((m) => [m.key, m]));
  it('reads values and never turns a missing value into 0', () => {
    expect(metricValue({ population: 10, pop500: null } as never, 'population')).toBe(10);
    expect(metricValue({ population: 10, pop500: null } as never, 'pop500')).toBeNull();
    expect(metricValue(null, 'population')).toBeNull();
  });
  it('explains empty 500m totals with the missing block, and the change rule', () => {
    expect(missingReason(byKey.workers500, { workers500: '다마 블록 2024년 종사자 파일 없음' })).toBe('다마 블록 2024년 종사자 파일 없음');
    expect(missingReason(byKey.pop_change_pct, {})).toBe('두 해 중 20명 미만 또는 통계 없음');
    expect(missingReason(byKey.housing500, {}, '제외')).toBe('500m 격자 통계를 받지 않은 지역');
    expect(missingReason(byKey.population, {})).toBe('자료 없음');
    expect(byKey.pop_change_pct.ramp).toBe('diff');
    expect(NATIONAL_METRICS.every((m) => m.definition && m.use)).toBe(true);
  });
  it('lists 도 first, then 특별시·광역시, in code order', () => {
    const groups = provinceGroups([{ code: '52', kind: 'PROVINCE' }, { code: '11', kind: 'METRO' }, { code: '41', kind: 'PROVINCE' }] as const as never as Array<{ code: string; kind: 'PROVINCE' | 'METRO' }>);
    expect(groups.map(([kind, items]) => [kind, items.map((i) => i.code)])).toEqual([['PROVINCE', ['41', '52']], ['METRO', ['11']]]);
  });
  it('shortens names for map chips and labels region levels', () => {
    expect(['경상북도', '전북특별자치도', '전남광주통합특별시', '서울특별시', '세종특별자치시', '경기도'].map(shortProvince)).toEqual(['경북', '전북', '전남광주', '서울', '세종', '경기']);
    expect(levelLabel('DETAILED')).toBe('상세 자료');
    expect(levelLabel('NONE')).toContain('처음 열면');
    expect(levelLabel('UNLINKED')).toContain('연결 안 됨');
  });
  it('picks the Korean topic particle after a name', () => {
    expect(withTopic('완주군')).toBe('완주군은');
    expect(withTopic('수원시')).toBe('수원시는');
    expect(withTopic('ABC')).toBe('ABC은(는)');
  });
});
