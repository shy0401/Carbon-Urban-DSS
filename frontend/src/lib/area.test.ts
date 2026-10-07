import { describe, expect, it } from 'vitest';
import { at, buildSpec, cohortOf, cohortSeries, complexFeatures, complexState, draftFeature, effortHeadline, eventYears, planBody, plannedArea, pvNote, type AreaHistory, type CarrierYear } from './area';

const empty: CarrierYear = { kwh: null, observed_parcels: 0, complete_parcels: 0, partial_parcels: 0, months_max: 0, by_cohort: {}, intensity_kwh_per_m2: null, intensity_area_m2: null, kwh_per_household: null, households: null };

function history(): AreaHistory {
  return {
    years: [2019, 2020, 2021],
    area: { type: 'admin', label: '덕진구 송천1동', method: '', geometry: null, grid_ids: [], complex_codes: [], admin_codes: [], admin_exact: true, admin_names: [] },
    energy: {
      '2019': { year: 2019, electricity: { ...empty, kwh: 1000, complete_parcels: 1, by_cohort: { '2010': 1000 } }, gas: empty, electricity_carbon_kgco2eq: 454.1, estimated: { kwh: 900, carbon_kgco2eq: 408.7, basis: '', data_class: 'ESTIMATED' } },
      '2020': { year: 2020, electricity: empty, gas: empty, electricity_carbon_kgco2eq: null, estimated: { kwh: 1500, carbon_kgco2eq: 681.2, basis: '', data_class: 'ESTIMATED' } },
      '2021': { year: 2021, electricity: { ...empty, kwh: 1800, complete_parcels: 3, by_cohort: { '2010': 1100, '2020': 500, '2021': 100, '미상': 100 } }, gas: empty, electricity_carbon_kgco2eq: 817.4, estimated: null },
    },
    weather: {}, population: {},
    events: { '2019': { year: 2019, complexes: 0, households: 0, gfa_m2: 0, names: [] }, '2020': { year: 2020, complexes: 1, households: 300, gfa_m2: 30000, names: ['가'] }, '2021': { year: 2021, complexes: 0, households: 0, gfa_m2: 0, names: [] } },
    stock: {}, factor: { electricity: 0.4541 }, factor_basis: '', complexes: [], city_intensity: null,
    coverage: { energy_years: [2019, 2021], weather_years: [], population_years: [], grid_count: 1, complex_count: 1 },
  };
}

describe('area helpers', () => {
  it('JSON 문자열 연도 키와 숫자 키를 모두 찾는다', () => {
    expect(at({ '2025': 1 }, 2025)).toBe(1);
    expect(at({ 2025: 2 } as Record<string, number>, 2025)).toBe(2);
    expect(at(undefined, 2025)).toBeUndefined();
  });

  it('선택 방식별 요청을 만들고 빠진 입력은 문장으로 돌려준다', () => {
    expect(buildSpec('admin', { code: '35012650' })).toEqual({ type: 'admin', code: '35012650' });
    expect(buildSpec('admin', {})).toMatch(/행정동/);
    expect(buildSpec('circle', { center: [127.1234567, 35.8765432], radius: 1500 })).toEqual({ type: 'circle', lon: 127.123457, lat: 35.876543, radius_m: 1500 });
    expect(buildSpec('circle', { center: [127, 35], radius: 50 })).toMatch(/100~5,000/);
    expect(buildSpec('circle', { radius: 500 })).toMatch(/중심점/);
    const polygon = buildSpec('polygon', { vertices: [[127, 35], [127.01, 35], [127.01, 35.01]] });
    expect(typeof polygon).toBe('object');
    if (typeof polygon === 'object') {
      expect(polygon.geometry?.coordinates[0]).toHaveLength(4);
      expect(polygon.geometry?.coordinates[0][3]).toEqual([127, 35]);
    }
    expect(buildSpec('polygon', { vertices: [[127, 35]] })).toMatch(/3개/);
    expect(buildSpec('zone', { category: 'COMMERCIAL' })).toEqual({ type: 'zone', category: 'COMMERCIAL' });
    expect(buildSpec('grid', { grid: null })).toMatch(/격자/);
  });

  it('계획 입력은 연면적 또는 층수×동수×건축면적 한쪽만 보낸다', () => {
    const plan = { method: 'massing' as const, added_floor_area_m2: 1, floors: 20, building_count: 5, footprint_per_building: 800, removed_floor_area_m2: 0 };
    expect(planBody(plan)).toEqual({ floors: 20, building_count: 5, footprint_per_building: 800 });
    expect(plannedArea(plan)).toBe(80000);
    expect(planBody({ ...plan, method: 'area', added_floor_area_m2: 50000, removed_floor_area_m2: 2000 })).toEqual({ added_floor_area_m2: 50000, removed_floor_area_m2: 2000 });
  });

  it('단지를 개발 연도 기준 기존·당해·이후·미상으로 나누고 슬라이더 연도 뒤 단지는 미준공으로 둔다', () => {
    expect(cohortOf(2018, 2020)).toBe('before');
    expect(cohortOf(2020, 2020)).toBe('event');
    expect(cohortOf(2022, 2020)).toBe('after');
    expect(cohortOf(null, 2020)).toBe('unknown');
    expect(complexState(2022, 2021, 2020)).toBe('future');
    expect(complexState(2021, 2021, 2020)).toBe('after');
    const fc = complexFeatures([{ kapt_code: 'A', name: '가', approval_year: 2021, approval_date: null, households: 10, gfa: 1, floor_area_ok: true, lon: 127, lat: 35, grid_id: null }, { kapt_code: 'B', name: '나', approval_year: 2000, approval_date: null, households: 5, gfa: 1, floor_area_ok: true, lon: null, lat: null, grid_id: null }], 2021, 2020);
    expect(fc.features).toHaveLength(1);
    expect(fc.features[0].properties).toMatchObject({ state: 'after', just_built: true });
  });

  it('관측이 없는 연도는 모든 계열이 null이고 추정선은 따로 둔다', () => {
    const s = cohortSeries(history(), 2020);
    expect(s.before).toEqual([1000, null, 1100]);
    expect(s.event).toEqual([0, null, 500]);
    expect(s.after).toEqual([0, null, 100]);
    expect(s.unknown).toEqual([0, null, 100]);
    expect(s.estimated).toEqual([900, 1500, null]);
    expect(eventYears(history())).toEqual([2020]);
  });

  it('감축 노력 문장은 엔진 결과의 달성 가능 여부를 따른다', () => {
    expect(effortHeadline({ available: false, reason: '근거 없음' })).toEqual({ tone: 'warn', text: '근거 없음' });
    expect(effortHeadline({ available: true, already_met: true, target_pct: 10 })?.tone).toBe('good');
    expect(effortHeadline({ available: true, already_met: false, feasible_with_new_only: true, target_pct: 5, options: { new_only_efficiency_pct: 62.5, all_buildings_efficiency_pct: 9, offset_kwh_per_year: 100, pv_capacity_kw: null, new_building_intensity_target: 11 } })?.text).toContain('62.5%');
    const hard = effortHeadline({ available: true, already_met: false, feasible_with_new_only: false, target_pct: 40, options: { new_only_efficiency_pct: 1473.1, all_buildings_efficiency_pct: 41.7, offset_kwh_per_year: 38320016.2, pv_capacity_kw: null, new_building_intensity_target: null } });
    expect(hard?.tone).toBe('bad');
    expect(hard?.text).toContain('41.7%');
    expect(hard?.text).toContain('38,320,016');
  });

  it('그리는 중인 구역은 3점 미만이면 선, 이상이면 닫힌 면이다', () => {
    expect(draftFeature([]).features).toHaveLength(0);
    expect(draftFeature([[0, 0], [1, 0]]).features[0].geometry.type).toBe('LineString');
    const poly = draftFeature([[0, 0], [1, 0], [1, 1]]).features[0].geometry as unknown as { coordinates: number[][][] };
    expect(poly.coordinates[0]).toHaveLength(4);
  });
});

describe('pvNote', () => {
  it('says whether the PV capacity uses the user number or the regional irradiation estimate', () => {
    expect(pvNote(null, null)).toContain('발전량을 넣으면');
    expect(pvNote({ kwh_per_kw: 1200, basis: 'USER', label: '사용자 입력' }, 10)).toBe('입력한 발전량 1,200 kWh/kW 기준');
    const est = { kwh_per_kw: 1047.2, basis: 'ESTIMATED' as const, label: '2025년 ERA5-Land 일사량 수평면 일사량 1,309 kWh/m² × 성능비 0.80', year: 2025, irradiation_kwh_m2: 1309, performance_ratio: 0.8 };
    expect(pvNote(est, 25.4)).toBe('추정: 2025년 ERA5-Land 일사량 수평면 일사량 1,309 kWh/m² × 성능비 0.80 = 1,047.2 kWh/kW·년');
  });
});
