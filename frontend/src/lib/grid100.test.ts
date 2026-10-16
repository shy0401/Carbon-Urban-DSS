import { describe, expect, it } from 'vitest';
import { GRID100_METRICS, grid100ClassLabel, grid100Classify, grid100Color, grid100Fill, grid100Lines, grid100Metric, grid100Tooltip, grid100Unavailable, grid100Value, populationText, type Grid100Props } from './grid100';

const cell = (over: Partial<Grid100Props> = {}): Grid100Props => ({
  id: 'g', x: 962000, y: 1748000, grid500: 'cell_962000_1748000', population: 120, population_status: 'observed',
  building_count: 6, floor_area_m2: 4200, approval_year: 1994.6, zone_class: 'residential', ...over,
});

const f = (over: Partial<Grid100Props> = {}) => ({ properties: cell(over) });

describe('100m grid (국토통계지도) helpers', () => {
  it('never turns a masked or blank population into 0', () => {
    expect(populationText(cell({ population: null, population_status: 'masked' }))).toBe('1~5명 (비공개)');
    expect(populationText(cell({ population: null, population_status: 'empty' }))).toBe('값 없음 (0인지 미확인)');
    expect(populationText(cell())).toBe('120 명');
    const lines = Object.fromEntries(grid100Lines(cell({ building_count: null, floor_area_m2: null, zone_class: null })));
    expect(lines['건물 수']).toBe('값 없음');
    expect(lines['추정 연면적']).toBe('값 없음');
    expect(lines['평균 사용승인']).toBe('1995년');
    expect(lines['용도지역']).toBe('값 없음');
  });
  it('classifies on fixed bounds and labels classes from the bounds, years without separators', () => {
    const metric = grid100Metric('approval_year');
    const c = grid100Classify([f({ approval_year: 2015 }), f({ approval_year: 2020 }), f({ approval_year: null })], metric);
    expect(c.lowerBounds).toEqual([1980, 1990, 2000, 2010]);
    expect(c.missing).toBe(1);
    expect(grid100ClassLabel(c, 0, metric)).toBe('1980년 이전');
    expect(grid100ClassLabel(c, 3, metric)).toBe('2000년 ~ 2010년 미만');
    expect(grid100ClassLabel(c, 4, metric)).toBe('2010년 이상');
    expect(grid100Value(1994.6, metric)).toBe('1995년');
    const pop = grid100Metric('population');
    const cp = grid100Classify([f({ population: 500 })], pop);
    expect(grid100ClassLabel(cp, 0, pop)).toBe('20 미만');
    expect(grid100ClassLabel(cp, 4, pop)).toBe('250 이상');
  });
  it('paints a cell without the value transparent, not with the lowest class', () => {
    const metric = grid100Metric('population');
    const c = grid100Classify([f({ population: 30 }), f({ population: 300 })], metric);
    expect(grid100Fill(null, c)).toBeNull();
    expect(grid100Fill(30, c)).toBe(c.classes[1].color);
    expect(grid100Fill(300, c)).toBe(c.classes[4].color);
    // every metric: every class has a colour of the 5-colour ramp (6 classes left the top one undefined and broke the MapLibre style)
    for (const m of GRID100_METRICS) {
      const k = grid100Classify([f({ population: 1, building_count: 1, floor_area_m2: 1, approval_year: 1970 })], m);
      expect(k.classes.every((cl) => typeof cl.color === 'string' && cl.color.startsWith('#'))).toBe(true);
      expect((grid100Color(m, k) as unknown[]).flat(Infinity).includes(undefined as never)).toBe(false);
    }
    const expr = grid100Color(metric, c) as unknown[];
    expect(expr[0]).toBe('case');
    expect(expr[2]).toEqual(['rgba', 0, 0, 0, 0]);
    expect(grid100Color(metric, grid100Classify([], metric))).toEqual(['rgba', 0, 0, 0, 0]);
  });
  it('escapes values in the popup and names the source year', () => {
    const html = grid100Tooltip(cell({ zone_class: '<b>x</b>' }), 2024);
    expect(html).toContain('국토통계지도 2024년');
    expect(html).toContain('&lt;b&gt;x&lt;/b&gt;');
    expect(html).not.toContain('<b>x</b>');
  });
  it('says why the layer is unavailable: public address, no data, or nothing collected', () => {
    expect(grid100Unavailable({ restricted: true })).toContain('국외 반출 금지');
    expect(grid100Unavailable(null)).toBeTruthy();
    expect(grid100Unavailable({ source: 's', years: [], year: null, cells: 0, returned: 0, truncated: false, reason: '이 지역에는 100m 격자 자료(국토통계지도)가 없습니다.' })).toContain('없습니다');
    expect(grid100Unavailable({ source: 's', years: [2024], year: 2024, cells: 10186, returned: 0, truncated: false, reason: null })).toBeNull();
  });
});
