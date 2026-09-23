import { describe, expect, it } from 'vitest';
import { provenanceFromCode, provenanceFromWeatherSource, sourceTypeLabel } from './provenance';

describe('근거 유형 매핑 (서버 필드만)', () => {
  it('서버 근거 코드를 배지 종류로 옮긴다', () => {
    expect(provenanceFromCode('OBSERVED')).toBe('observed');
    expect(provenanceFromCode('CALCULATED')).toBe('computed');
    expect(provenanceFromCode('ESTIMATED')).toBe('estimated');
    expect(provenanceFromCode('SCENARIO')).toBe('scenario');
    expect(provenanceFromCode('FALLBACK')).toBe('fallback');
    expect(provenanceFromCode('NOT_COLLECTED')).toBe('missing');
  });
  it('코드가 없거나 자유 문장이면 배지를 만들지 않는다(추론 금지)', () => {
    expect(provenanceFromCode(undefined)).toBeNull();
    expect(provenanceFromCode(null)).toBeNull();
    expect(provenanceFromCode('공간매칭된 관측 / 표본 범위 확인')).toBeNull();
    expect(provenanceFromCode('SUCCESS')).toBeNull();
  });
  it('기상 행의 source_type으로 실측·대체를 구분한다', () => {
    expect(provenanceFromWeatherSource('OFFICIAL')).toBe('observed');
    expect(provenanceFromWeatherSource('FALLBACK')).toBe('fallback');
    expect(provenanceFromWeatherSource(undefined)).toBeNull();
    expect(sourceTypeLabel('DERIVED')).toBe('파생');
  });
});
