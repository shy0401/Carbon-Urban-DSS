import { describe, expect, it } from 'vitest';
import { bandText, caseError, readingOf, signed, siteLabel, statusText } from './teamModel';

describe('teamModel', () => {
  it('reads small changes as a direction only and shows the 80% band otherwise', () => {
    expect(readingOf(999)).toBe('direction');
    expect(readingOf(-1000)).toBe('value');
    expect(signed(2500)).toBe('+2,500');
    expect(signed(-12.4)).toBe('−12');
    expect(signed(null)).toBe('—');
    expect(bandText({ q10: 900, q25: 1500, q75: 3000, q90: 4100 })).toBe('+900 ~ +4,100 tCO₂e (80% 구간)');
    expect(bandText({ q10: -100, q90: -900 })).toBe('−900 ~ −100 tCO₂e (80% 구간)');
    expect(bandText({})).toBeNull();
  });

  it('scores a case the team way and names the model state', () => {
    expect(caseError({ set: 'test', actual_tco2e: 1000, pred_tco2e: 1300 })).toBeCloseTo(0.3);
    expect(caseError({ set: 'test', actual_tco2e: 50, pred_tco2e: 1300 })).toBeNull();  // below 100 tCO2e: not scored
    expect(caseError(null)).toBeNull();
    expect(siteLabel('new_site')).toBe('빈 땅 신축');
    expect(statusText({ status: 'training' })).toContain('학습하는 중');
    expect(statusText({ status: 'ready', train_seconds: 95.2, train: '00_합본_7차' })).toBe('학습 완료 (95초) · 00_합본_7차');
    expect(statusText({ status: 'off', reason: '꺼져 있습니다' })).toBe('꺼져 있습니다');
  });
});
