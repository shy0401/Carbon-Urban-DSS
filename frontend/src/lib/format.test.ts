import { describe, expect, it } from 'vitest';
import { formatMetric, qualityLabel } from './format';

describe('formatMetric', () => {
  it('결측 관측값을 0이 아니라 자료 없음으로 표시한다', () => {
    expect(formatMetric(null, 'kWh')).toBe('자료 없음');
    expect(formatMetric(undefined, 'kgCO₂')).toBe('자료 없음');
  });

  it('유효한 0은 실제 측정값으로 표시한다', () => {
    expect(formatMetric(0, 'kWh')).toBe('0 kWh');
  });

  it('품질 코드를 한국어 설명으로 바꾼다', () => {
    expect(qualityLabel('FALLBACK')).toBe('대체 자료');
    expect(qualityLabel(null)).toBe('미평가');
  });
});
