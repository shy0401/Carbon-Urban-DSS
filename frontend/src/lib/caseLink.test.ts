import { describe, expect, it } from 'vitest';
import { areaLink, parseAreaLink, parseScenarioLink, scenarioLink } from './caseLink';
import type { ScenarioInput } from '../types';

const plan: ScenarioInput = { site_area: 40000, building_count: 10, footprint_per_building: 600, floors: 15, households: 1000, population: 2500, efficiency_factor: 1, pv_ratio: 0, green_ratio: 0.3, average_household_area: 84 };

describe('사례 링크', () => {
  it('시뮬레이션 입력·지역·격자·대지 위치가 주소를 오가도 같다', () => {
    const path = scenarioLink(plan, { lon: 127.13219, lat: 35.880124, rotation: 0 }, { region: '41110', grid: 'cell_950000_1919000', year: 2025 }, { min_households: 900, min_population: 2200 });
    const back = parseScenarioLink(path.split('?')[1]);
    expect(back?.input).toEqual(plan);
    expect(back?.site).toEqual({ lon: 127.13219, lat: 35.880124, rotation: 0 });
    expect([back?.region, back?.grid, back?.year]).toEqual(['41110', 'cell_950000_1919000', 2025]);
    // 전주(최초 연구 지역)는 범위에서 null이지만 링크에는 늘 코드를 적어, 다른 지역을 보던 사람도 전주로 연다
    expect(scenarioLink(plan, null, { region: null })).toMatch(/^\/simulation\?region=52110&site_area=40000/);
    expect(parseScenarioLink('region=52110')?.region).toBeNull();
    expect(back?.constraints).toEqual({ min_households: 900, min_population: 2200 });
  });

  it('주소에 입력이 없으면 화면 기본값을 그대로 쓰고, 이상한 값은 버린다', () => {
    expect(parseScenarioLink('')).toBeNull();
    const odd = parseScenarioLink('floors=abc&site=1,2&grid=../x&region=9&site_area=-5');
    expect(odd?.input).toEqual({});
    expect(odd?.site).toBeUndefined();
    expect(odd?.grid).toBeUndefined();
    expect(odd?.region).toBeNull();   // not a 5-digit code → the original region
  });

  it('지역 시뮬레이션 구역·기간·계획·목표·기준 건물', () => {
    const base = { region: '52110', from: 2015, to: 2025, event: null, window: 3, target: 20, pv: '', basis: 'buildings' as const,
      plan: { method: 'area' as const, added_floor_area_m2: 75000, floors: 20, building_count: 5, footprint_per_building: 800, removed_floor_area_m2: 0 } };
    const path = areaLink({ type: 'admin', code: '35011790' }, base)!;
    expect(path).toBe('/area?region=52110&area=admin:35011790&from=2015&to=2025&window=3&plan=75000&target=20&basis=buildings');
    const back = parseAreaLink(path.split('?')[1]);
    expect(back).toMatchObject({ region: null, mode: 'admin', spec: { type: 'admin', code: '35011790' }, from: 2015, to: 2025, window: 3, target: 20, basis: 'buildings',
      plan: { method: 'area', added_floor_area_m2: 75000 } });
    const circle = parseAreaLink('area=circle:127.13219,35.880124,1000&pv=1200');
    expect(circle?.spec).toEqual({ type: 'circle', lon: 127.13219, lat: 35.880124, radius_m: 1000 });
    expect(circle?.pv).toBe('1200');
    expect(parseAreaLink('area=zone:COMMERCIAL')?.spec).toEqual({ type: 'zone', category: 'COMMERCIAL' });
    expect(areaLink({ type: 'polygon', geometry: { type: 'Polygon', coordinates: [] } }, base)).toBeNull();
    expect(parseAreaLink('area=admin:abc')?.spec).toBeUndefined();
  });

  it('감축 수단 조합(mx)은 값이 있을 때만 링크에 넣고 다시 읽는다', () => {
    const base = { region: '52710', from: 2015, to: 2025, event: null, window: 3, target: 40, pv: '', basis: 'apartments' as const,
      plan: { method: 'area' as const, added_floor_area_m2: 50000, floors: 20, building_count: 5, footprint_per_building: 800, removed_floor_area_m2: 0 } };
    expect(areaLink({ type: 'admin', code: '35510410' }, { ...base, measures: { new_efficiency_pct: 0, existing_efficiency_pct: 0, pv_kw: 0 } })).not.toContain('mx=');
    const path = areaLink({ type: 'admin', code: '35510410' }, { ...base, measures: { new_efficiency_pct: 30, existing_efficiency_pct: 5, pv_kw: 120.5 } })!;
    expect(path).toMatch(/&mx=30,5,120.5$/);
    expect(parseAreaLink(path.split('?')[1])?.measures).toEqual({ new_efficiency_pct: 30, existing_efficiency_pct: 5, pv_kw: 120.5 });
    expect(parseAreaLink('area=admin:35510410&mx=130,0,0')?.measures).toBeUndefined();   // over 100%: ignored
    expect(parseAreaLink('area=admin:35510410&mx=1,2')?.measures).toBeUndefined();
  });
});
