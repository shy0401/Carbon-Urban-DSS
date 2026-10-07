import type { DongData, GridProps } from '../types';
import type { MetricDef } from './mapMetrics';

/**
 * 격자 지표를 읍면동(행정동)으로 모으는 규칙.
 *
 * 격자마다 "행정동 안에 든 면적 비율"(share, 0~1)이 있다(서버가 행정동 경계와 겹친 면적 ÷ 250,000㎡로 계산).
 * - 합계 지표(연간 전력·가스·탄소, 건물 수, 세대수): Σ 격자 값 × share. 값 없는 격자는 0이 아니라 빠지고,
 *   "값 있는 면적 비율"(coverage)을 같이 보여 준다 — 합계는 관측된 부분의 합이지 동 전체의 참값이 아니다.
 * - 원단위·비율 지표: 가중 평균. 가중치는 그 비율의 분모(연면적·세대수·건물 수·대장 연면적)가 있으면 그것 × share,
 *   없으면 겹친 면적(share)이다.
 * - 인구·가구는 SGIS 행정동 공식 값을 먼저 보여 준다. 500m 격자 통계(주택·종사자 등)는 합계 규칙으로 모은다.
 */
export const SUM_KEYS = new Set([
  'electricity_kwh_annual', 'gas_kwh_annual', 'electricity_carbon_t', 'gas_carbon_t', 'bldg_electricity_kwh', 'bldg_gas_kwh', 'bldg_carbon_t', 'bldg_gas_carbon_t',
  'building_count', 'complex_households', 'complex_count', 'reg_buildings', 'reg_gfa_m2',
  'sgis500_population', 'sgis500_households', 'sgis500_housing', 'sgis500_workers',
]);
export const WEIGHT_KEYS: Record<string, string> = {
  electricity_kwh_per_m2: 'electricity_area_m2', gas_kwh_per_m2: 'gas_area_m2', electricity_carbon_kg_per_m2: 'electricity_area_m2',
  electricity_kwh_per_household: 'electricity_households', bldg_kwh_per_m2: 'bldg_area_m2', avg_floors: 'building_count',
  residential_building_share: 'building_count', reg_residential_gfa_pct: 'reg_gfa_m2', reg_old_gfa_pct: 'reg_gfa_m2',
  // 기준연도 인구로 가중하면 Σ(증감)/Σ(기준 인구), 곧 동 전체의 증감률이 된다 (두 해 모두 20명 이상인 격자만).
  sgis500_pop_change_pct: 'sgis500_base_population',
};

export interface DongAggregate {
  value: number | null;
  kind: 'sum' | 'mean';
  /** Share (0~1) of the 행정동's cell area where the metric has a value. */
  coverage: number;
  /** Cells with a value that touch the 행정동. */
  valuedCells: number;
}

const num = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);

/** cell id → share for one 행정동 (index into ``data.dongs``). */
export function dongCells(data: DongData | null, index: number): Map<string, number> {
  const out = new Map<string, number>();
  if (!data || index < 0) return out;
  for (const [cell, pairs] of Object.entries(data.weights)) for (const [i, share] of pairs) if (i === index) out.set(cell, share);
  return out;
}

/** The 행정동 with the largest part of each cell (for tooltips). */
export function mainDong(data: DongData | null, cell: string): number | null {
  const pairs = data?.weights[cell];
  if (!pairs?.length) return null;
  return pairs.reduce((best, pair) => (pair[1] > best[1] ? pair : best))[0];
}

export function aggregate(key: string, value: (p: GridProps) => number | null, props: Map<string, GridProps>, shares: Map<string, number>): DongAggregate {
  const kind = SUM_KEYS.has(key) ? 'sum' : 'mean';
  const weightKey = WEIGHT_KEYS[key];
  let total = 0, weight = 0, covered = 0, area = 0, valuedCells = 0;
  for (const [cell, share] of shares) {
    area += share;
    const p = props.get(cell);
    const v = p ? value(p) : null;
    if (v === null) continue;
    if (kind === 'sum') { total += v * share; covered += share; valuedCells += 1; continue; }
    const w = weightKey ? num(p?.[weightKey]) : 1;
    if (w === null || w <= 0) continue;
    total += v * w * share; weight += w * share; covered += share; valuedCells += 1;
  }
  const coverage = area > 0 ? covered / area : 0;
  if (!valuedCells) return { value: null, kind, coverage: 0, valuedCells: 0 };
  return { value: kind === 'sum' ? total : weight > 0 ? total / weight : null, kind, coverage, valuedCells };
}

export function aggregateMetric(metric: Pick<MetricDef, 'key' | 'value'>, props: Map<string, GridProps>, shares: Map<string, number>): DongAggregate {
  return aggregate(metric.key, metric.value, props, shares);
}

export interface DongRank { index: number; name: string; result: DongAggregate }

/** Every 행정동 with the metric aggregated, highest first; 행정동 without values last (never ranked as 0). */
export function rankDongs(data: DongData | null, metric: Pick<MetricDef, 'key' | 'value'>, props: Map<string, GridProps>): DongRank[] {
  if (!data) return [];
  const shares = data.dongs.map(() => new Map<string, number>());
  for (const [cell, pairs] of Object.entries(data.weights)) for (const [i, share] of pairs) shares[i]?.set(cell, share);
  return data.dongs.map((dong, index) => ({ index, name: dong.name, result: aggregateMetric(metric, props, shares[index]) }))
    .sort((a, b) => (b.result.value ?? -Infinity) - (a.result.value ?? -Infinity) || a.name.localeCompare(b.name, 'ko'));
}

/** Ray casting on one ring ([lon, lat] pairs). */
function inRing(x: number, y: number, ring: number[][]): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i]; const [xj, yj] = ring[j];
    if ((yi > y) !== (yj > y) && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}

export function pointInGeometry(x: number, y: number, geometry: GeoJSON.Geometry | null | undefined): boolean {
  if (!geometry) return false;
  const polygons = geometry.type === 'Polygon' ? [geometry.coordinates] : geometry.type === 'MultiPolygon' ? geometry.coordinates : [];
  return polygons.some((rings) => rings.length > 0 && inRing(x, y, rings[0]) && !rings.slice(1).some((hole) => inRing(x, y, hole)));
}

export interface DongComplexes { count: number; households: number; withHouseholds: number }

/** K-apt 단지 points counted in the 행정동 that contains them (exact, not spread by cell shares). */
export function complexesByDong(data: DongData | null, complexes: GeoJSON.FeatureCollection | null | undefined): DongComplexes[] {
  const out = (data?.dongs ?? []).map(() => ({ count: 0, households: 0, withHouseholds: 0 }));
  if (!data || !complexes) return out;
  const boxes = data.boundaries.features.map((f) => {
    const xs: number[] = [], ys: number[] = [];
    const visit = (v: unknown) => { if (Array.isArray(v) && typeof v[0] === 'number') { xs.push(v[0] as number); ys.push(v[1] as number); } else if (Array.isArray(v)) v.forEach(visit); };
    visit((f.geometry as { coordinates?: unknown }).coordinates);
    return { i: f.properties.i, geometry: f.geometry, box: [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)] };
  });
  for (const feature of complexes.features) {
    if (feature.geometry?.type !== 'Point') continue;
    const [x, y] = feature.geometry.coordinates;
    const hit = boxes.find((b) => x >= b.box[0] && x <= b.box[2] && y >= b.box[1] && y <= b.box[3] && pointInGeometry(x, y, b.geometry));
    if (!hit || !out[hit.i]) continue;
    const households = num(feature.properties?.households);
    out[hit.i].count += 1;
    if (households !== null) { out[hit.i].households += households; out[hit.i].withHouseholds += 1; }
  }
  return out;
}
