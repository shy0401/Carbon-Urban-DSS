/**
 * 지역 시뮬레이션 화면의 순수 함수와 응답 형식.
 * 숫자는 모두 서버 계산 엔진(/api/areas/analyze)이 만든 값이며, 여기서는 표시용으로 고르거나 묶기만 한다.
 * JSON은 연도 키를 문자열로 바꾸므로("2025") 조회는 항상 at()으로 한다.
 */
import { TOKENS } from '../theme/palette';
import type { SgisGridSummary } from '../types';

export type AreaMode = 'admin' | 'circle' | 'polygon' | 'zone' | 'grid';
export type ZoneCategory = 'RESIDENTIAL' | 'COMMERCIAL' | 'INDUSTRIAL' | 'GREEN' | 'OTHER';

export interface AreaSpec {
  type: AreaMode;
  code?: string;
  grid_id?: string;
  lon?: number;
  lat?: number;
  radius_m?: number;
  category?: string;
  geometry?: { type: 'Polygon'; coordinates: number[][][] };
  label?: string;
}

export interface AreaOptions {
  admin: Array<{ code: string; name: string }>;
  admin_geojson: GeoJSON.FeatureCollection;
  admin_year: number | null;
  zones: Array<{ category: string; label: string; grids: number }>;
  energy_years: number[];
  default_grid: string | null;
}

export interface CarrierYear {
  kwh: number | null;
  observed_parcels: number;
  complete_parcels: number;
  partial_parcels: number;
  months_max: number;
  by_cohort: Record<string, number>;
  intensity_kwh_per_m2: number | null;
  intensity_area_m2: number | null;
  kwh_per_household: number | null;
  households: number | null;
}

export interface EnergyYear {
  year: number;
  electricity: CarrierYear;
  gas: CarrierYear;
  electricity_carbon_kgco2eq: number | null;
  estimated?: { kwh: number | null; carbon_kgco2eq: number | null; basis: string; data_class: string } | null;
}

export interface EventYear { year: number; complexes: number; households: number; gfa_m2: number; names: string[] }
export interface StockYear { year: number; complexes: number; households: number; gfa_m2: number; gfa_excluded: number; unknown_approval: number }
export interface WeatherYear { year: number; months: number; complete: boolean; hdd: number | null; cdd: number | null; mean_temperature: number | null; sources: string[] }
export interface PopulationYear { year: number; population: number | null; households: number | null; dongs: number; basis: string }

export interface AreaComplex {
  kapt_code: string;
  name: string;
  approval_year: number | null;
  approval_date: string | null;
  households: number | null;
  gfa: number | null;
  floor_area_ok: boolean;
  lon: number | null;
  lat: number | null;
  grid_id: string | null;
  heating_type?: string | null;
}

type YearTable<T> = Record<string, T>;

export interface AreaHistory {
  years: number[];
  area: {
    type: AreaMode;
    label: string;
    method: string;
    geometry: GeoJSON.Geometry | null;
    grid_ids: string[];
    complex_codes: string[];
    admin_codes: string[];
    admin_exact: boolean;
    admin_names: string[];
    admin_labels?: string[];
  };
  energy: YearTable<EnergyYear>;
  weather: YearTable<WeatherYear>;
  population: YearTable<PopulationYear>;
  events: YearTable<EventYear>;
  stock: YearTable<StockYear>;
  factor: { electricity?: number | null };
  factor_basis: string;
  complexes: AreaComplex[];
  city_intensity: { year: number; kwh_per_m2: number; area_m2: number; parcels: number } | null;
  coverage: { energy_years: number[]; weather_years: number[]; population_years: number[]; grid_count: number; complex_count: number; register_buildings?: number };
  register?: RegisterHistory;
  sgis_grid?: AreaSgisGrid | null;
  building_energy?: AreaBuildingEnergy;
}

/** 건축HUB 법정동 단위 전 지번 (2024-): 구역 격자 안 계측 건물 전체. */
export interface AreaBuildingEnergy {
  available: boolean;
  basis: string;
  years: YearTable<{ year: number; parcels: number; electricity_complete: number; electricity_kwh: number | null; gas_complete: number; gas_kwh: number | null; area_m2: number | null; kwh_per_m2: number | null; electricity_carbon_kgco2eq: number | null; complete?: boolean }>;
}

/** SGIS 1km 격자 통계 (구역이 걸친 1km 격자 전체 합계 = 관측, 면적 비례 값 = 추정). */
export interface AreaSgisGrid {
  year: number;
  cells: number;
  cells_with_stats: number;
  coverage_pct: number | null;
  overlap: SgisGridSummary | null;
  estimated: { population: number | null; households: number | null; data_class: 'ESTIMATED'; basis: string };
  source: string;
}

/** 건축물대장 사용승인 (모든 용도, 격자 기준). */
export interface RegisterHistory {
  available: boolean;
  linked_in_area: number;
  unknown_year: number;
  basis: string;
  years: YearTable<{ year: number; buildings: number; gfa_m2: number; gfa_missing: number; by_use: Record<string, number> }>;
}

export const REGISTER_GROUPS = ['주거', '상업·업무', '공공·교육·의료', '공업·창고·물류', '기타·미상'] as const;

export interface CarrierComparison {
  before_total_kwh: number | null;
  after_total_kwh: number | null;
  total_change_kwh: number | null;
  total_change_pct: number | null;
  existing_before_kwh: number | null;
  existing_after_kwh: number | null;
  existing_change_pct: number | null;
  new_development_kwh: number | null;
  new_share_pct: number | null;
}

export interface BeforeAfter {
  available: boolean;
  reason?: string;
  event_year?: number;
  window?: number;
  before_years?: number[];
  after_years?: number[];
  event?: EventYear;
  metrics?: {
    electricity: CarrierComparison;
    gas: CarrierComparison;
    electricity_carbon: Record<string, number | null>;
    estimated?: {
      before_kwh: number | null; after_kwh: number | null; change_kwh: number | null; change_pct: number | null;
      added_gfa_m2: number | null; data_class: string; event_added_kwh?: number | null; event_change_pct?: number | null; prior_gfa_m2?: number | null;
    } | null;
  };
  weather?: { before_hdd: number | null; after_hdd: number | null; before_cdd: number | null; after_cdd: number | null };
  population?: { before: number | null; after: number | null; basis: string };
  gaps?: string[];
}

export interface EffortResult {
  available: boolean;
  reason?: string;
  baseline_year?: number;
  target_pct?: number;
  baseline_mode?: 'OBSERVED' | 'ESTIMATED';
  data_class?: string;
  intensity_kwh_per_m2?: number;
  intensity_area_m2?: number;
  added_floor_area_m2?: number;
  removed_floor_area_m2?: number;
  baseline_kwh?: number;
  baseline_kgco2eq?: number;
  new_load_kwh?: number;
  bau_kwh?: number;
  bau_kgco2eq?: number;
  target_kgco2eq?: number;
  required_reduction_kgco2eq?: number;
  already_met?: boolean;
  feasible_with_new_only?: boolean;
  options?: {
    new_only_efficiency_pct: number | null;
    all_buildings_efficiency_pct: number | null;
    offset_kwh_per_year: number | null;
    pv_capacity_kw: number | null;
    new_building_intensity_target: number | null;
  };
  curve?: Array<{ target_pct: number; all_buildings_efficiency_pct: number | null; new_only_efficiency_pct: number | null }>;
  factor_kgco2eq_per_kwh?: number;
  scope?: string;
  assumptions?: string[];
}

export interface AreaFact { id: string; text: string; numbers?: number[] }

export interface AreaAnalysis {
  history: AreaHistory;
  before_after: BeforeAfter;
  effort: EffortResult | null;
  grid_features: GeoJSON.FeatureCollection;
  facts: AreaFact[];
  admin_year: number | null;
}

export interface AreaReport {
  id: string;
  title: string;
  created_at: string;
  area: AreaHistory['area'];
  facts: AreaFact[];
  evidence_hash: string;
  summary: { mode: 'TEMPLATE' | 'LOCAL_SLM_NARRATIVE' | 'TEMPLATE_FALLBACK'; model: string | null; paragraphs: string[]; validation: string; violations: string[]; reason?: string; rejected?: string };
}

export interface PlanState {
  method: 'area' | 'massing';
  added_floor_area_m2: number;
  floors: number;
  building_count: number;
  footprint_per_building: number;
  removed_floor_area_m2: number;
}

/** Year-keyed lookup that accepts the string keys JSON gives back. */
export function at<T>(table: Record<string, T> | undefined, year: number): T | undefined {
  if (!table) return undefined;
  return table[String(year)] ?? (table as Record<number, T>)[year];
}

export const MODE_LABEL: Record<AreaMode, string> = { admin: '행정동', circle: '반경(지도 클릭)', polygon: '직접 그리기', zone: '용도지역', grid: '기준 격자' };

/** Request body for the chosen area. Returns an error message instead when the input is incomplete. */
export function buildSpec(mode: AreaMode, input: { code?: string; category?: string; grid?: string | null; center?: [number, number] | null; radius?: number; vertices?: Array<[number, number]> }): AreaSpec | string {
  switch (mode) {
    case 'admin': return input.code ? { type: 'admin', code: input.code } : '행정동을 고르거나 지도에서 동을 누르세요.';
    case 'zone': return input.category ? { type: 'zone', category: input.category } : '용도지역을 고르세요.';
    case 'grid': return input.grid ? { type: 'grid', grid_id: input.grid } : '기준 격자가 없습니다.';
    case 'circle': {
      if (!input.center) return '지도에서 중심점을 누르세요.';
      const radius = Number(input.radius);
      if (!Number.isFinite(radius) || radius < 100 || radius > 5000) return '반경은 100~5,000m 입니다.';
      return { type: 'circle', lon: round6(input.center[0]), lat: round6(input.center[1]), radius_m: radius };
    }
    case 'polygon': {
      const points = input.vertices ?? [];
      if (points.length < 3) return '지도에서 꼭짓점을 3개 이상 찍으세요.';
      const ring = points.map(([x, y]) => [round6(x), round6(y)]);
      ring.push([...ring[0]]);
      return { type: 'polygon', geometry: { type: 'Polygon', coordinates: [ring] }, label: `직접 그린 구역 (${points.length}각형)` };
    }
  }
}

const round6 = (v: number) => Math.round(v * 1e6) / 1e6;

export function planBody(plan: PlanState): Record<string, number> {
  const body: Record<string, number> = plan.method === 'massing'
    ? { floors: plan.floors, building_count: plan.building_count, footprint_per_building: plan.footprint_per_building }
    : { added_floor_area_m2: plan.added_floor_area_m2 };
  if (plan.removed_floor_area_m2 > 0) body.removed_floor_area_m2 = plan.removed_floor_area_m2;
  return body;
}

export function plannedArea(plan: PlanState): number {
  return plan.method === 'massing' ? plan.floors * plan.building_count * plan.footprint_per_building : plan.added_floor_area_m2;
}

/** Cohort of a complex relative to the development year being compared. */
export type Cohort = 'before' | 'event' | 'after' | 'unknown';
export const COHORT_LABEL: Record<Cohort, string> = { before: '기존 단지', event: '개발 연도 단지', after: '이후 단지', unknown: '승인일 미상' };
/** 기존 = 중립 회색(배경 재고), 개발 연도 = plan-b, 이후 = 보라. 검증: CVD ΔE 28.8, 호박색은 3:1 미만이라 범례·표로 보조. */
export const COHORT_COLOR: Record<Cohort, string> = { before: TOKENS['ink-3'], event: TOKENS['plan-b'], after: '#5E4BA0', unknown: TOKENS.hatch };

export function cohortOf(approvalYear: number | null | undefined, eventYear: number | null | undefined): Cohort {
  if (!approvalYear) return 'unknown';
  if (!eventYear) return 'before';
  return approvalYear < eventYear ? 'before' : approvalYear === eventYear ? 'event' : 'after';
}

/** Map state of a complex at the slider year: not built yet, or built with its cohort. */
export function complexState(approvalYear: number | null | undefined, sliderYear: number, eventYear: number | null | undefined): Cohort | 'future' {
  if (approvalYear && approvalYear > sliderYear) return 'future';
  return cohortOf(approvalYear, eventYear);
}

/** GeoJSON points for the complexes, with the state for the slider year in `state`. */
export function complexFeatures(complexes: AreaComplex[], sliderYear: number, eventYear: number | null | undefined): GeoJSON.FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: complexes.filter((c) => typeof c.lon === 'number' && typeof c.lat === 'number').map((c) => ({
      type: 'Feature',
      geometry: { type: 'Point', coordinates: [c.lon as number, c.lat as number] },
      properties: { code: c.kapt_code, name: c.name, households: c.households ?? 0, approval_year: c.approval_year, state: complexState(c.approval_year, sliderYear, eventYear), just_built: c.approval_year === sliderYear },
    })),
  };
}

/**
 * Observed electricity (12-month complete parcels only) per year, split by cohort relative to the event year.
 * A year without any complete parcel stays null in every series (drawn as "자료 없음", never zero).
 */
export function cohortSeries(history: AreaHistory, eventYear: number | null | undefined) {
  const out: Record<Cohort, Array<number | null>> = { before: [], event: [], after: [], unknown: [] };
  const estimated: Array<number | null> = [];
  for (const year of history.years) {
    const e = at(history.energy, year);
    const kwh = e?.electricity.kwh;
    estimated.push(e?.estimated?.kwh ?? null);
    if (kwh === null || kwh === undefined) { (Object.keys(out) as Cohort[]).forEach((k) => out[k].push(null)); continue; }
    const sums: Record<Cohort, number> = { before: 0, event: 0, after: 0, unknown: 0 };
    for (const [key, value] of Object.entries(e?.electricity.by_cohort ?? {})) {
      const cohort = cohortOf(/^\d{4}$/.test(key) ? Number(key) : null, eventYear);
      sums[cohort] += value;
    }
    (Object.keys(out) as Cohort[]).forEach((k) => out[k].push(sums[k]));
  }
  return { ...out, estimated };
}

/** Years that have an approval event (candidates for the before/after comparison). */
export function eventYears(history: AreaHistory): number[] {
  return history.years.filter((y) => (at(history.events, y)?.households ?? 0) > 0 || (at(history.events, y)?.complexes ?? 0) > 0);
}

/** One-line reading of the effort result for the headline (numbers straight from the engine). */
export function effortHeadline(effort: EffortResult | null | undefined): { tone: 'good' | 'warn' | 'bad'; text: string } | null {
  if (!effort) return null;
  if (!effort.available) return { tone: 'warn', text: effort.reason ?? '감축 노력을 계산할 근거가 없습니다.' };
  if (effort.already_met) return { tone: 'good', text: `계획을 반영해도 목표 ${effort.target_pct}% 감축선 아래입니다. 추가 감축이 필요하지 않습니다.` };
  const o = effort.options;
  if (effort.feasible_with_new_only && o?.new_only_efficiency_pct !== null && o?.new_only_efficiency_pct !== undefined) {
    return { tone: 'warn', text: `신축 건물만으로 달성하려면 신축 부하를 ${o.new_only_efficiency_pct}% 줄여야 합니다.` };
  }
  return { tone: 'bad', text: `신축만으로는 달성할 수 없습니다. 지역 전체 건물의 전력 사용을 ${o?.all_buildings_efficiency_pct ?? '—'}% 줄이거나 연 ${formatInt(o?.offset_kwh_per_year)} kWh를 재생에너지로 상쇄해야 합니다.` };
}

function formatInt(value: number | null | undefined) { return value === null || value === undefined ? '—' : new Intl.NumberFormat('ko-KR', { maximumFractionDigits: 0 }).format(value); }

export const REPORT_MODE_LABEL: Record<AreaReport['summary']['mode'], string> = {
  TEMPLATE: '검증된 서식 문장',
  LOCAL_SLM_NARRATIVE: '로컬 AI 문장 (숫자 검증 통과)',
  TEMPLATE_FALLBACK: '로컬 AI 문장 불채택 → 검증된 서식',
};

/** Closed ring for drawing the polygon being edited (open line while < 3 points). */
export function draftFeature(vertices: Array<[number, number]>): GeoJSON.FeatureCollection {
  if (!vertices.length) return { type: 'FeatureCollection', features: [] };
  const points: GeoJSON.Feature[] = vertices.map((v, i) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: v }, properties: { i } }));
  const line: GeoJSON.Feature = vertices.length >= 3
    ? { type: 'Feature', geometry: { type: 'Polygon', coordinates: [[...vertices, vertices[0]]] }, properties: {} }
    : { type: 'Feature', geometry: { type: 'LineString', coordinates: vertices }, properties: {} };
  return { type: 'FeatureCollection', features: [line, ...points] };
}
