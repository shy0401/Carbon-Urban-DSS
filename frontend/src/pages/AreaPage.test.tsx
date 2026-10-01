import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { AreaPage } from './AreaPage';

vi.mock('../components/Chart', () => ({ Chart: ({ ariaLabel }: { ariaLabel: string }) => <div role="img" aria-label={ariaLabel} /> }));
vi.mock('../components/area/AreaMap', () => ({ AreaMap: () => <div data-testid="area-map" /> }));

const carrier = { kwh: null, observed_parcels: 0, complete_parcels: 0, partial_parcels: 0, months_max: 0, by_cohort: {}, intensity_kwh_per_m2: null, intensity_area_m2: null, kwh_per_household: null, households: null };
const year = (y: number, est: number) => ({ year: y, electricity: carrier, gas: carrier, electricity_carbon_kgco2eq: null, estimated: { kwh: est, carbon_kgco2eq: est * 0.4541, basis: '연면적 × 원단위', data_class: 'ESTIMATED' } });
const analysis = {
  history: {
    years: [2018, 2019, 2020],
    area: { type: 'admin', label: '덕진구 송천1동 (행정동)', method: '행정동 경계 안', geometry: null, grid_ids: ['g1'], complex_codes: ['A'], admin_codes: ['35012650'], admin_exact: true, admin_names: ['송천1동'] },
    energy: { '2018': year(2018, 100), '2019': year(2019, 150), '2020': year(2020, 160) },
    weather: {}, population: {},
    events: { '2018': { year: 2018, complexes: 0, households: 0, gfa_m2: 0, names: [] }, '2019': { year: 2019, complexes: 1, households: 500, gfa_m2: 50000, names: ['에코시티'] }, '2020': { year: 2020, complexes: 0, households: 0, gfa_m2: 0, names: [] } },
    stock: { '2018': { year: 2018, complexes: 1, households: 300, gfa_m2: 30000, gfa_excluded: 0, unknown_approval: 0 }, '2019': { year: 2019, complexes: 2, households: 800, gfa_m2: 80000, gfa_excluded: 0, unknown_approval: 0 }, '2020': { year: 2020, complexes: 2, households: 800, gfa_m2: 80000, gfa_excluded: 0, unknown_approval: 0 } },
    factor: { electricity: 0.4541 }, factor_basis: '최신 계수 동일 적용', complexes: [], city_intensity: { year: 2025, kwh_per_m2: 30.97, area_m2: 1000, parcels: 3 },
    coverage: { energy_years: [], weather_years: [], population_years: [], grid_count: 1, complex_count: 2 },
  },
  before_after: { available: true, event_year: 2019, window: 1, before_years: [2018], after_years: [2020], event: { year: 2019, complexes: 1, households: 500, gfa_m2: 50000, names: ['에코시티'] }, metrics: { electricity: { before_total_kwh: null, after_total_kwh: null, total_change_kwh: null, total_change_pct: null, existing_before_kwh: null, existing_after_kwh: null, existing_change_pct: null, new_development_kwh: null, new_share_pct: null }, gas: {}, electricity_carbon: {}, estimated: { before_kwh: 100, after_kwh: 160, change_kwh: 60, change_pct: 60, added_gfa_m2: 50000, data_class: 'ESTIMATED', event_added_kwh: 1548500, event_change_pct: 166.7, prior_gfa_m2: 30000 } }, weather: { before_hdd: null, after_hdd: null, before_cdd: null, after_cdd: null }, population: { before: null, after: null, basis: '행정동 값' }, gaps: ['전후 기간에 12개월이 모두 관측된 전력 자료가 부족합니다 (과거 수집 필요)'] },
  effort: { available: true, baseline_year: 2020, target_pct: 40, baseline_mode: 'ESTIMATED', data_class: 'SCENARIO', intensity_kwh_per_m2: 30.97, intensity_area_m2: 80000, added_floor_area_m2: 50000, removed_floor_area_m2: 0, baseline_kwh: 2477600, baseline_kgco2eq: 1125078.2, new_load_kwh: 1548500, bau_kwh: 4026100, bau_kgco2eq: 1828252, target_kgco2eq: 675046.9, required_reduction_kgco2eq: 1153205.1, already_met: false, feasible_with_new_only: false, options: { new_only_efficiency_pct: 164, all_buildings_efficiency_pct: 63.1, offset_kwh_per_year: 2539540, pv_capacity_kw: null, new_building_intensity_target: null }, curve: [{ target_pct: 0, all_buildings_efficiency_pct: 38.5, new_only_efficiency_pct: 100 }], scope: '전력 운영탄소 기준', assumptions: ['기상은 기준 연도와 같다고 가정합니다'] },
  grid_features: { type: 'FeatureCollection', features: [] },
  facts: [{ id: 'scope', text: '분석 대상은 덕진구 송천1동 (행정동)이고 기간은 2018~2020년입니다.', numbers: [2018, 2020] }],
  admin_year: 2024,
};

describe('AreaPage', () => {
  afterEach(() => vi.restoreAllMocks());

  it('첫 행정동을 분석하고 관측이 없는 값은 0이 아니라 자료 없음으로, 감축 노력은 엔진 값 그대로 보여 준다', async () => {
    const bodies: unknown[] = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith('/api/areas/options')) return new Response(JSON.stringify({ admin: [{ code: '35011600', name: '완산구 동서학동' }, { code: '35012650', name: '덕진구 송천1동' }], admin_geojson: { type: 'FeatureCollection', features: [] }, admin_year: 2024, zones: [{ category: 'COMMERCIAL', label: '상업지역', grids: 18 }], energy_years: [2025], default_grid: 'cell_1' }));
      if (url.endsWith('/api/areas/collection')) return new Response(JSON.stringify({ items: {}, runs: [], summary: {} }));
      if (url.endsWith('/api/areas/analyze')) { bodies.push(JSON.parse(String(init?.body))); return new Response(JSON.stringify(analysis)); }
      if (url.endsWith('/api/area-reports')) return new Response(JSON.stringify([]));
      return new Response('{}', { status: 404 });
    });
    render(<AreaPage />);
    expect(await screen.findByRole('heading', { name: '덕진구 송천1동 (행정동)' })).toBeInTheDocument();
    await waitFor(() => expect(bodies.length).toBeGreaterThan(0));
    expect(bodies[0]).toMatchObject({ area: { type: 'admin', code: '35012650' }, from_year: 2015, to_year: 2025, target_pct: 40, plan: { added_floor_area_m2: 50000 } });
    expect(screen.getByText('과거 전력을 아직 수집하지 않았습니다.')).toBeInTheDocument();
    expect(screen.getByText(/scripts\\dss.cmd CollectAll/)).toBeInTheDocument();
    expect(screen.getByText("건축물대장을 아직 수집하지 않았습니다")).toBeInTheDocument();
    expect(screen.getByText(/지역 전체 건물의 전력 사용을 63.1% 줄이거나/)).toBeInTheDocument();
    expect(screen.getByText('164 % 필요 → 불가')).toBeInTheDocument();
    expect(screen.getByText('전후 기간에 12개월이 모두 관측된 전력 자료가 부족합니다 (과거 수집 필요)')).toBeInTheDocument();
    expect(screen.getAllByText('자료 없음').length).toBeGreaterThan(0);
    expect(screen.getByText('SGIS 격자 통계를 아직 가져오지 않았습니다')).toBeInTheDocument();
  });

  it('감축 노력의 기준을 건물 전체(건축HUB)로 바꾸면 그 기준으로 다시 계산을 요청한다', async () => {
    const bodies: Array<Record<string, unknown>> = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith('/api/areas/options')) return new Response(JSON.stringify({ admin: [{ code: '35011790', name: '완산구 효자5동' }], admin_geojson: { type: 'FeatureCollection', features: [] }, admin_year: 2024, zones: [], energy_years: [2025], default_grid: 'cell_1' }));
      if (url.endsWith('/api/areas/collection')) return new Response(JSON.stringify({ items: {}, runs: [], summary: {} }));
      if (url.endsWith('/api/areas/analyze')) {
        const body = JSON.parse(String(init?.body)); bodies.push(body);
        const basis = body.effort_basis === 'buildings' ? 'buildings' : 'apartments';
        return new Response(JSON.stringify({ ...analysis, effort: { ...analysis.effort, basis, baseline_mode: 'OBSERVED' } }));
      }
      if (url.endsWith('/api/area-reports')) return new Response(JSON.stringify([]));
      return new Response('{}', { status: 404 });
    });
    render(<AreaPage />);
    await waitFor(() => expect(bodies.length).toBeGreaterThan(0));
    expect(bodies[0]).toMatchObject({ effort_basis: 'apartments' });
    (await screen.findByRole('tab', { name: '건물 전체 (건축HUB)' })).click();
    await waitFor(() => expect(bodies.some((b) => b.effort_basis === 'buildings')).toBe(true), { timeout: 3000 });
    expect(await screen.findByText(/기준 부하 관측 · 2020년 · 건물 전체 \(건축HUB\)/)).toBeInTheDocument();
  });

  it('SGIS 1km 격자 합계는 관측, 면적 비례 인구는 추정으로 따로 보여 준다', async () => {
    const sgis = {
      year: 2024, cells: 3, cells_with_stats: 2, coverage_pct: 33.3, source: 'SGIS',
      estimated: { population: 12182, households: 6315, data_class: 'ESTIMATED', basis: '1km 격자 값 × (구역에 든 500m 격자 수 ÷ 4)' },
      overlap: { population: 34609, male: null, female: null, households: 17644, housing: 11482, businesses: null, workers: 18697, elderly_pct: 20.7, children_pct: null, single_household_pct: 57.5, old_housing_pct: 58.5, apartment_pct: 47.7,
        housing_age: {}, housing_types: {}, housing_area: {}, household_types: {}, sectors: [], small_flags: [] },
    };
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => {
      const url = String(input);
      if (url.endsWith('/api/areas/options')) return new Response(JSON.stringify({ admin: [{ code: '35012650', name: '덕진구 송천1동' }], admin_geojson: { type: 'FeatureCollection', features: [] }, admin_year: 2024, zones: [], energy_years: [2025], default_grid: 'cell_1' }));
      if (url.endsWith('/api/areas/collection')) return new Response(JSON.stringify({ items: {}, runs: [], summary: {} }));
      if (url.endsWith('/api/areas/analyze')) return new Response(JSON.stringify({ ...analysis, history: { ...analysis.history, sgis_grid: sgis } }));
      if (url.endsWith('/api/area-reports')) return new Response(JSON.stringify([]));
      return new Response('{}', { status: 404 });
    });
    render(<AreaPage />);
    expect(await screen.findByText('지역 특성 (SGIS 1km 격자 2024년)')).toBeInTheDocument();
    expect(screen.getByText('34,609 명')).toBeInTheDocument();
    expect(screen.getByText('구역 인구 (면적 비례 추정)')).toBeInTheDocument();
    expect(screen.getByText('12,182 명')).toBeInTheDocument();
    expect(screen.getByText('33.3%')).toBeInTheDocument();
  });
});
