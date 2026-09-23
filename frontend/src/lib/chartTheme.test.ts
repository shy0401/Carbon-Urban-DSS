import { describe, expect, it } from 'vitest';
import { lineSeries, missingRuns, monthsOf } from './chartTheme';

describe('chart rules', () => {
  it('결측 월은 0이 아니라 null로 남기고 선을 잇지 않는다', () => {
    const values = monthsOf(2025, [{ use_ym: '202501', t: 1.2 }, { use_ym: '202503', t: 9 }], 't');
    expect(values).toHaveLength(12);
    expect(values[0]).toBe(1.2);
    expect(values[1]).toBeNull();
    expect(values[11]).toBeNull();
    expect(lineSeries('x', values, '#000000').connectNulls).toBe(false);
  });
  it('모든 계열이 비는 달을 연속 구간으로 묶어 해치 띠를 만든다', () => {
    expect(missingRuns([[1, null, null, 4, null], [2, null, 3, null, null]], 5)).toEqual([[1, 1], [4, 4]]);
    expect(missingRuns([[null, null, 1]], 3)).toEqual([[0, 1]]);
  });
  it('근거 유형을 선 모양으로 구분한다', () => {
    expect(lineSeries('a', [], '#000000').lineStyle.type).toBe('solid');
    expect(lineSeries('b', [], '#000000', 'estimated').lineStyle.type).toEqual([4, 3]);
    expect(lineSeries('c', [], '#000000', 'scenario').lineStyle.type).toEqual([1, 3]);
  });
});
