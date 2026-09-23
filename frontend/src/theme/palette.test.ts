import { describe, expect, it } from 'vitest';
import css from '../styles/tokens.css?raw';
import { GAIN_RAMP, LOAD_RAMP, SEQ_RAMP, TOKENS, USE_GROUP_COLOR, ZONE_GROUP_COLOR, zoneToken } from './palette';

const cssTokens = Object.fromEntries([...css.matchAll(/--([a-z0-9-]+):\s*(#[0-9a-fA-F]{3,8})\b/g)].map((m) => [m[1], m[2].toUpperCase()]));

function luminance(hex: string) {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}
function contrast(a: string, b: string) { const [x, y] = [luminance(a), luminance(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); }

describe('palette.ts ↔ tokens.css', () => {
  it('색 토큰의 키와 값이 두 파일에서 같다', () => {
    const palette = Object.fromEntries(Object.entries(TOKENS).map(([k, v]) => [k, v.toUpperCase()]));
    expect(Object.keys(cssTokens).length).toBeGreaterThan(80);
    expect(palette).toEqual(cssTokens);
  });

  it('DESIGN.md 2.1·2.3의 핵심 값을 그대로 쓴다', () => {
    expect(TOKENS.canvas).toBe('#F3F3EE');
    expect(TOKENS['nav-bg']).toBe('#1F3A33');
    expect(TOKENS['prov-estimated']).toBe('#7A5418');
    expect(TOKENS.hatch).toBe('#CFCBBF');
    expect(LOAD_RAMP).toEqual(['#F1EAD9', '#E2C58F', '#CC9350', '#A65B2B', '#6A2E17']);
    expect(GAIN_RAMP.at(-1)).toBe('#2C6343');
  });

  it('순차 램프는 밝은 색에서 어두운 색으로 단조 감소한다', () => {
    for (const ramp of [LOAD_RAMP, GAIN_RAMP, SEQ_RAMP]) {
      const values = ramp.map(luminance);
      values.slice(1).forEach((value, i) => expect(value).toBeLessThan(values[i]));
    }
  });

  it('글자 대비 4.5:1 — 캡션(--ink-3)은 흰 바탕 전용, 도면지·표 머리 위에는 --ink-2 이상', () => {
    for (const ink of [TOKENS.ink, TOKENS['ink-2'], TOKENS['ink-3']]) expect(contrast(ink, TOKENS.surface)).toBeGreaterThanOrEqual(4.5);
    for (const bg of [TOKENS.canvas, TOKENS['surface-sunk'], TOKENS['prov-missing-bg']]) {
      expect(contrast(TOKENS['ink-2'], bg)).toBeGreaterThanOrEqual(4.5);
      // DESIGN.md 8: --ink-3 on these backgrounds is below 4.5:1, so the CSS never puts captions there.
      expect(contrast(TOKENS['ink-3'], bg)).toBeLessThan(4.5);
    }
    for (const kind of ['observed', 'computed', 'estimated', 'scenario'] as const) {
      expect(contrast(TOKENS[`prov-${kind}`], TOKENS[`prov-${kind}-bg`])).toBeGreaterThanOrEqual(4.5);
    }
    // 결측 배지 글자는 --prov-missing(4.2:1) 대신 --ink-2를 쓴다.
    expect(contrast(TOKENS['ink-2'], TOKENS['prov-missing-bg'])).toBeGreaterThanOrEqual(4.5);
    for (const [fg, bg] of [['danger', 'danger-bg'], ['warning', 'warning-bg'], ['success', 'success-bg'], ['info', 'info-bg']] as const) {
      expect(contrast(TOKENS[fg], TOKENS[bg])).toBeGreaterThanOrEqual(4.5);
    }
    expect(contrast(TOKENS['nav-ink'], TOKENS['nav-bg'])).toBeGreaterThanOrEqual(4.5);
    expect(contrast(TOKENS['nav-ink-2'], TOKENS['nav-bg'])).toBeGreaterThanOrEqual(4.5);
    expect(contrast(TOKENS['nav-ink'], TOKENS['nav-active'])).toBeGreaterThanOrEqual(4.5);
    expect(contrast(TOKENS['on-primary'], TOKENS.primary)).toBeGreaterThanOrEqual(4.5);
    // 입력 테두리(비텍스트 3:1)는 --ink-3을 쓴다.
    expect(contrast(TOKENS['ink-3'], TOKENS.surface)).toBeGreaterThanOrEqual(3);
  });

  it('용도지역 공식 명칭을 세부 토큰으로, 모르는 이름은 해치(null)로 둔다', () => {
    expect(zoneToken('제2종일반주거지역')).toBe('zone-r2');
    expect(zoneToken('제1종전용주거지역')).toBe('zone-r1e');
    expect(zoneToken('준주거지역')).toBe('zone-rq');
    expect(zoneToken('자연녹지지역')).toBe('zone-gn');
    expect(zoneToken('보전관리지역')).toBe('zone-m');
    expect(zoneToken('')).toBeNull();
    expect(zoneToken('미지정')).toBeNull();
    expect(ZONE_GROUP_COLOR.UNKNOWN).toBeNull();
    expect(USE_GROUP_COLOR.UNKNOWN).toBeNull();
  });
});
