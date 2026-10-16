import { describe, expect, it } from 'vitest';
import { kcsmClassify, kcsmClassLabel, kcsmColor, kcsmFill, kcsmFromFeature, kcsmLines, kcsmTooltip, kcsmUnavailable, kcsmValueText, KCSM_ZERO_FILL, type KcsmProps } from './kcsm100';

const cell = (over: Partial<KcsmProps> = {}): KcsmProps => ({
  id: '다마555632', x: 955500, y: 1763200, grid500: 'cell_955500_1763000', elec_t: 120, status: 'value',
  prev_year: 2023, prev_t: 100, change_pct: 20, drop: false, drop_from_t: null, ...over,
});
const f = (over: Partial<KcsmProps> = {}) => ({ properties: cell(over) });

describe('탄소공간지도 100m 전기 배출 helpers', () => {
  it('keeps a provider 0 apart from a missing value and from the lowest class', () => {
    const c = kcsmClassify([f({ elec_t: 0, status: 'zero' }), f({ elec_t: 30 }), f({ elec_t: 2000 })]);
    expect(c.valued).toBe(2);                       // the 0 cell is not classified as a value
    expect(kcsmFill(cell({ elec_t: 0, status: 'zero' }), c)).toBe(KCSM_ZERO_FILL);
    expect(kcsmFill(cell({ elec_t: null, status: 'missing' }), c)).toBeNull();
    expect(kcsmFill(cell({ elec_t: 30 }), c)).toBe(c.classes[1].color);
    expect(kcsmValueText({ elec_t: 0 })).toContain('확인 필요');
    expect(kcsmValueText({ elec_t: null })).toBe('값 없음');
    const expr = kcsmColor(c) as unknown[];
    expect(expr[0]).toBe('case');
    expect(expr[2]).toBe(KCSM_ZERO_FILL);
    expect(kcsmClassLabel(c, 0)).toBe('10 미만');
    expect(kcsmClassLabel(c, 5)).toBe('1,000 이상');
  });
  it('names the previous year, the change and a suspected drop, and escapes the popup', () => {
    const lines = Object.fromEntries(kcsmLines(cell({ elec_t: 0, status: 'zero', prev_t: 360, change_pct: -100, drop: true, drop_from_t: 360 }), 2024));
    expect(lines['2023년']).toContain('−100.0%'.replace('−', '-'));
    expect(lines['표시']).toContain('누락 의심');
    expect(kcsmTooltip(cell({ id: '<x>' }), 2024)).not.toContain('<x>');
  });
  it('reads MapLibre feature properties (dropped nulls, strings) back into numbers', () => {
    const p = kcsmFromFeature({ id: 'a', x: '1', y: '2', grid500: 'g', elec_t: '0', drop: 'true', prev_t: 'null' });
    expect(p.elec_t).toBe(0); expect(p.status).toBe('zero'); expect(p.drop).toBe(true); expect(p.prev_t).toBeNull(); expect(p.change_pct).toBeNull();
  });
  it('says why the layer is off', () => {
    expect(kcsmUnavailable({ restricted: true })).toContain('공개 주소');
    expect(kcsmUnavailable({ source: 's', years: [], year: null, cells: 0, returned: 0, truncated: false, reason: '이 지역에는 없습니다' })).toBe('이 지역에는 없습니다');
    expect(kcsmUnavailable({ source: 's', years: [2023, 2024], year: 2024, cells: 21036, returned: 0, truncated: false, reason: null })).toBeNull();
  });
});
