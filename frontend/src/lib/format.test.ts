import { describe, expect, it } from 'vitest';
import { formatMetric, qualityLabel, withTo } from './format';

describe('formatMetric', () => {
  it('결측 관측값을 0이 아니라 자료 없음으로 표시한다', () => {
    expect(formatMetric(null, 'kWh')).toBe('자료 없음');
    expect(formatMetric(undefined, 'kgCO₂')).toBe('자료 없음');
  });

  it('유효한 0은 실제 측정값으로 표시한다', () => {
    expect(formatMetric(0, 'kWh')).toBe('0 kWh');
  });

  it('fixed면 소수 자리를 맞추고 천 단위 쉼표를 넣는다', () => {
    expect(formatMetric(39, 'kWh/m²·년', 1, true)).toBe('39.0 kWh/m²·년');
    expect(formatMetric(48.54, '', 1, true)).toBe('48.5');
    expect(formatMetric(318619, 'm²')).toBe('318,619 m²');
  });

  it('품질 코드를 한국어 설명으로 바꾼다', () => {
    expect(qualityLabel('FALLBACK')).toBe('대체 자료');
    expect(qualityLabel(null)).toBe('미평가');
  });

  it('예전 수집 기록의 smoke·limited 같은 개발 용어를 화면 말로 바꾼다', () => {
    expect(qualityLabel('유효 12행 / smoke 수집')).toBe('유효 12행 / 첫 검증 수집');
    expect(qualityLabel('법정동 3곳(limited) / 일시 오류 0건')).toBe('법정동 3곳(일부 수집) / 일시 오류 0건');
  });
});

describe('withTo', () => {
  it('받침에 맞춰 (으)로를 붙인다', () => {
    expect(withTo('완주군')).toBe('완주군으로');
    expect(withTo('전주시')).toBe('전주시로');
    expect(withTo('수원시 팔달구')).toBe('수원시 팔달구로');
    expect(withTo('52710')).toBe('52710(으)로');
  });
});
