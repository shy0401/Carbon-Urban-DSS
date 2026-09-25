import type { GridProps } from '../types';
import { RAMPS, TOKENS, type RampName } from '../theme/palette';
import { USE_NAME, ZONE_NAME } from './labels';
import { formatMetric } from './format';

/** One map indicator: what it is, how it is computed, and the basis for a given grid. */
export interface MetricDef {
  key: string;
  label: string;
  unit: string;
  group: string;
  digits: number;
  /** 램프 (DESIGN.md 2.4): load = 높을수록 나쁨, gain = 높을수록 좋음, seq = 방향성 없음. */
  ramp: RampName;
  value: (p: GridProps) => number | null;
  definition: string;
  formula: string;
  basis: (p: GridProps) => string | null;
  /** Fixed class lower bounds (after the first class). Default: quantiles of the data. */
  breaks?: number[];
  source: string;
  note?: string;
}

const n = (value: unknown): number | null => (typeof value === 'number' && Number.isFinite(value) ? value : null);
const fmt = (value: number | null | undefined, unit = '', digits = 0) => formatMetric(value, unit, digits);
const GRID = '250,000 m²';
export const SGIS_GROUP = '인구·주택 (SGIS 1km)';
const SGIS_SOURCE = 'SGIS 격자 통계 1km (공공데이터포털 15141768)';
const SGIS_NOTE = '이 500m 격자가 속한 1km 공식 격자의 값입니다. 같은 1km 격자의 500m 격자 4개는 같은 값이며, 500m로 나눈 값이 아닙니다. 비밀보호 잡음(인구 ±7)이 들어 있습니다.';
const sgisBasis = (p: GridProps, extra: string | null) =>
  p.sgis1k_status === 'OBSERVED' ? `1km 격자 ${p.sgis1k_code} · ${p.sgis1k_year}년${extra ? ` · ${extra}` : ''}` : null;
export const PERCENT_BREAKS = [20, 40, 60, 80];

export const METRIC_GROUPS = ['에너지 관측', '에너지 원단위', '탄소', '도시 형태', '토지이용', SGIS_GROUP, '데이터 품질'] as const;

export const METRICS: MetricDef[] = [
  {
    key: 'electricity_kwh_annual', label: '연간 전력 사용량', unit: 'kWh/년', group: '에너지 관측', ramp: 'load', digits: 0,
    value: (p) => n(p.electricity_kwh_annual),
    definition: '격자 안에서 12개월 모두 관측된 지번(공동주택 단지)의 전력 사용량 합계입니다. 격자 안 모든 건물의 합이 아닙니다.',
    formula: 'Σ 월별 전력(kWh), 12개월 관측 지번만',
    basis: (p) => p.electricity_complete_parcels ? `12개월 관측 지번 ${p.electricity_complete_parcels}곳 합계${p.electricity_observed_parcels > p.electricity_complete_parcels ? ` · 일부 월만 관측된 ${p.electricity_observed_parcels - p.electricity_complete_parcels}곳 제외` : ''}` : null,
    source: '건축HUB 건물에너지 · K-apt 월별 에너지',
  },
  {
    key: 'gas_kwh_annual', label: '연간 가스 사용량', unit: 'kWh/년', group: '에너지 관측', ramp: 'load', digits: 0,
    value: (p) => n(p.gas_kwh_annual),
    definition: '12개월 모두 관측된 지번의 도시가스 사용량(건축HUB kWh 환산값) 합계입니다.',
    formula: 'Σ 월별 가스(kWh), 12개월 관측 지번만',
    basis: (p) => p.gas_complete_parcels ? `12개월 관측 지번 ${p.gas_complete_parcels}곳 합계` : null,
    source: '건축HUB 건물에너지',
  },
  {
    key: 'electricity_kwh_per_m2', label: '전력 원단위', unit: 'kWh/m²·년', group: '에너지 원단위', ramp: 'load', digits: 1,
    value: (p) => n(p.electricity_kwh_per_m2),
    definition: '연면적 1m²당 연간 전력 사용량입니다. 연면적은 K-apt 공표값이며 비현실적인 값(세대당 20~400m² 밖)은 제외합니다.',
    formula: 'Σ 연간 전력 ÷ Σ 연면적 (같은 지번 집합)',
    basis: (p) => p.electricity_area_m2 ? `지번 ${p.electricity_area_parcels}곳 · 연면적 ${fmt(p.electricity_area_m2, 'm²')} 기준` : null,
    source: '에너지 관측 ÷ K-apt 연면적',
  },
  {
    key: 'electricity_kwh_per_household', label: '세대당 전력', unit: 'kWh/세대·년', group: '에너지 원단위', ramp: 'load', digits: 0,
    value: (p) => n(p.electricity_kwh_per_household),
    definition: '공동주택 1세대당 연간 전력 사용량(공용 포함)입니다. 월평균은 이 값 ÷ 12입니다.',
    formula: 'Σ 연간 전력 ÷ Σ 세대수 (같은 지번 집합)',
    basis: (p) => p.electricity_households ? `지번 ${p.electricity_household_parcels}곳 · ${fmt(p.electricity_households, '세대')} 기준 · 월평균 ${fmt((p.electricity_kwh_per_household ?? 0) / 12, 'kWh', 0)}` : null,
    source: '에너지 관측 ÷ K-apt 세대수',
  },
  {
    key: 'gas_kwh_per_m2', label: '가스 원단위', unit: 'kWh/m²·년', group: '에너지 원단위', ramp: 'load', digits: 1,
    value: (p) => n(p.gas_kwh_per_m2),
    definition: '연면적 1m²당 연간 가스 사용량(kWh 환산)입니다.',
    formula: 'Σ 연간 가스 ÷ Σ 연면적 (같은 지번 집합)',
    basis: (p) => p.gas_area_m2 ? `지번 ${p.gas_area_parcels}곳 · 연면적 ${fmt(n(p.gas_area_m2), 'm²')} 기준` : null,
    source: '건축HUB ÷ K-apt 연면적',
  },
  {
    key: 'electricity_carbon_t', label: '전력 탄소배출량', unit: 'tCO₂eq/년', group: '탄소', ramp: 'load', digits: 1,
    value: (p) => { const kg = n(p.electricity_carbon_kg_annual); return kg === null ? null : kg / 1000; },
    definition: '연간 전력 사용량에 국가 승인 전력 배출계수를 곱한 운영탄소입니다. 가스 탄소는 계수 확정 전이라 포함하지 않습니다.',
    formula: '연간 전력(kWh) × 0.4541 kgCO₂eq/kWh ÷ 1,000',
    basis: (p) => p.electricity_kwh_annual ? `${fmt(n(p.electricity_kwh_annual), 'kWh')} × 0.4541 (GIR 2024 소비단)` : null,
    source: 'GIR 2024 승인 국가 온실가스 배출계수',
  },
  {
    key: 'electricity_carbon_kg_per_m2', label: '전력 탄소 원단위', unit: 'kgCO₂eq/m²·년', group: '탄소', ramp: 'load', digits: 1,
    value: (p) => n(p.electricity_carbon_kg_per_m2),
    definition: '연면적 1m²당 연간 전력 탄소배출량입니다.',
    formula: '전력 원단위(kWh/m²) × 0.4541',
    basis: (p) => p.electricity_area_m2 ? `지번 ${p.electricity_area_parcels}곳 · 연면적 ${fmt(p.electricity_area_m2, 'm²')} 기준` : null,
    source: '전력 원단위 × GIR 계수',
  },
  {
    key: 'building_count', label: '건물 수', unit: '동', group: '도시 형태', ramp: 'seq', digits: 0,
    value: (p) => n(p.building_count),
    definition: '대표점이 격자 안에 있는 건물 수입니다. 공식 도로명주소 건물(VWorld)이 없으면 OSM 공동주택 윤곽으로 대체합니다.',
    formula: '격자 안 건물 대표점 개수',
    basis: (p) => p.building_source === 'OSM' ? 'OSM 공동주택 윤곽만 포함 (전체 건물 아님)' : p.building_count !== null ? `밀도 ${fmt(n(p.building_density), '동/km²', 0)}` : null,
    source: 'VWorld LT_C_SPBD (대체: OSM)',
  },
  {
    key: 'coverage_pct', label: '건폐율 근사', unit: '%', group: '도시 형태', ramp: 'seq', digits: 1,
    value: (p) => n(p.coverage_pct), breaks: [5, 10, 20, 30],
    definition: '격자 면적 중 건물이 덮은 면적의 비율입니다. 필지 대지면적 기준의 법정 건폐율과는 다릅니다.',
    formula: `Σ 건축면적 ÷ ${GRID} × 100`,
    basis: (p) => p.footprint_m2 !== null ? `건축면적 ${fmt(p.footprint_m2, 'm²')} ÷ ${GRID}` : null,
    source: 'VWorld 건물 윤곽 면적',
  },
  {
    key: 'far_est_pct', label: '추정 용적률', unit: '%', group: '도시 형태', ramp: 'seq', digits: 1,
    value: (p) => n(p.far_est_pct), breaks: [25, 50, 100, 200],
    definition: '건축면적 × 지상층수로 추정한 연면적을 격자 면적으로 나눈 값입니다. 층수가 없는 건물은 빠지며 법정 용적률이 아닙니다.',
    formula: `Σ(건축면적 × 지상층수) ÷ ${GRID} × 100`,
    basis: (p) => p.floor_area_est_m2 !== null ? `추정 연면적 ${fmt(p.floor_area_est_m2, 'm²')} · 층수 확인 ${fmt(p.floors_known_pct, '%', 0)}` : null,
    source: 'VWorld 건물 윤곽 × 지상층수',
  },
  {
    key: 'avg_floors', label: '평균 지상층수', unit: '층', group: '도시 형태', ramp: 'seq', digits: 1,
    value: (p) => n(p.avg_floors), breaks: [2, 4, 8, 15],
    definition: '층수가 기록된 건물의 지상층수 평균입니다.',
    formula: 'Σ 지상층수 ÷ 층수 확인 건물 수',
    basis: (p) => p.avg_floors !== null ? `최고 ${fmt(p.max_floors, '층')} · 층수 확인 ${fmt(p.floors_known_pct, '%', 0)}` : null,
    source: 'VWorld 건물 지상층수',
  },
  {
    key: 'complex_households', label: '공동주택 세대수', unit: '세대', group: '도시 형태', ramp: 'seq', digits: 0,
    value: (p) => n(p.complex_households),
    definition: '위치가 격자 안에 있는 K-apt 의무관리 공동주택 단지의 세대수 합계입니다.',
    formula: 'Σ 단지 세대수',
    basis: (p) => p.complex_count ? `단지 ${p.complex_count}개` : null,
    source: 'K-apt 공동주택 기본정보',
  },
  {
    key: 'residential_zone_ratio', label: '주거지역 비율', unit: '%', group: '토지이용', ramp: 'seq', digits: 1,
    value: (p) => n(p.residential_zone_ratio), breaks: PERCENT_BREAKS,
    definition: '격자 면적 중 법정 주거지역(제1·2·3종 일반주거 등) 도형과 겹치는 면적의 비율입니다.',
    formula: `주거지역 ∩ 격자 면적 ÷ ${GRID} × 100`,
    basis: (p) => p.zone_shares ? Object.entries(p.zone_shares).sort((a, b) => b[1] - a[1]).map(([k, v]) => `${ZONE_NAME[k] ?? k} ${v.toFixed(1)}%`).join(' · ') : null,
    source: 'VWorld LT_C_UQ111 용도지역',
  },
  {
    key: 'residential_building_share', label: '주거용 건물 비중', unit: '%', group: '토지이용', ramp: 'seq', digits: 1,
    value: (p) => n(p.residential_building_share), breaks: PERCENT_BREAKS,
    definition: '격자 안 건물 건축면적 중 주거용(단독·공동주택) 건물의 비율입니다.',
    formula: '주거용 건축면적 ÷ 전체 건축면적 × 100',
    basis: (p) => p.use_share_pct ? Object.entries(p.use_share_pct).sort((a, b) => b[1] - a[1]).slice(0, 3).map(([k, v]) => `${USE_NAME[k] ?? k} ${v.toFixed(1)}%`).join(' · ') : null,
    source: 'VWorld 건물용도코드',
  },
  {
    key: 'sgis_pop_density', label: '인구밀도', unit: '명/km²', group: SGIS_GROUP, ramp: 'seq', digits: 0,
    value: (p) => n(p.sgis_pop_density),
    definition: `${SGIS_NOTE} 1km 격자는 1km²이므로 총인구가 곧 인구밀도입니다. 통계가 없는 격자(인구가 없거나 비공개)는 0이 아니라 결측으로 둡니다.`,
    formula: '1km 격자 총인구(to_in_001) ÷ 1 km²',
    basis: (p) => sgisBasis(p, p.sgis1k_households != null ? `가구 ${fmt(p.sgis1k_households, '')}` : null),
    breaks: [100, 1000, 5000, 10000], source: SGIS_SOURCE,
  },
  {
    key: 'sgis_housing_density', label: '주택밀도', unit: '호/km²', group: SGIS_GROUP, ramp: 'seq', digits: 0,
    value: (p) => n(p.sgis_housing_density),
    definition: `${SGIS_NOTE} 주택은 총주택(거처) 수입니다.`,
    formula: '1km 격자 총주택(to_ho_001) ÷ 1 km²',
    basis: (p) => sgisBasis(p, null),
    breaks: [50, 500, 2000, 4000], source: SGIS_SOURCE,
  },
  {
    key: 'sgis_worker_density', label: '종사자밀도', unit: '명/km²', group: SGIS_GROUP, ramp: 'seq', digits: 0,
    value: (p) => n(p.sgis_worker_density),
    definition: `${SGIS_NOTE} 종사자는 사업체 종사자 수(사업체 부문 잡음 ±4)입니다. 상업·업무 활동의 크기를 봅니다.`,
    formula: '1km 격자 총종사자(to_em_020) ÷ 1 km²',
    basis: (p) => sgisBasis(p, p.sgis1k_businesses != null ? `사업체 ${fmt(p.sgis1k_businesses, '곳')}` : null),
    breaks: [100, 500, 2000, 5000], source: SGIS_SOURCE,
  },
  {
    key: 'sgis_elderly_pct', label: '65세 이상 비율', unit: '%', group: SGIS_GROUP, ramp: 'seq', digits: 1,
    value: (p) => n(p.sgis_elderly_pct), breaks: [15, 25, 35, 45],
    definition: `${SGIS_NOTE} 연령별 인구 합이 20명 미만이면 잡음이 커서 비율을 내지 않습니다.`,
    formula: '65세 이상 인구(in_age_014~021) ÷ 연령별 인구 합 × 100',
    basis: (p) => sgisBasis(p, null), source: SGIS_SOURCE,
  },
  {
    key: 'sgis_single_household_pct', label: '1인가구 비율', unit: '%', group: SGIS_GROUP, ramp: 'seq', digits: 1,
    value: (p) => n(p.sgis_single_household_pct), breaks: [25, 35, 45, 60],
    definition: `${SGIS_NOTE} 총가구가 20 미만이면 비율을 내지 않습니다.`,
    formula: '1인가구(ga_sd_005) ÷ 총가구(to_ga_001) × 100',
    basis: (p) => sgisBasis(p, null), source: SGIS_SOURCE,
  },
  {
    key: 'sgis_old_housing_pct', label: '2000년 이전 주택 비율', unit: '%', group: SGIS_GROUP, ramp: 'seq', digits: 1,
    value: (p) => n(p.sgis_old_housing_pct), breaks: PERCENT_BREAKS,
    definition: `${SGIS_NOTE} 1999년 이전에 지어진 주택의 비율입니다. 노후 주택이 많은 곳은 개보수 효과를 검토할 후보입니다.`,
    formula: '건축연도 1999년 이전 주택(ho_yr_001~003) ÷ 건축연도별 주택 합 × 100',
    basis: (p) => sgisBasis(p, null), source: SGIS_SOURCE,
  },
  {
    key: 'sgis_apartment_pct', label: '아파트 비율', unit: '%', group: SGIS_GROUP, ramp: 'seq', digits: 1,
    value: (p) => n(p.sgis_apartment_pct), breaks: PERCENT_BREAKS,
    definition: `${SGIS_NOTE} K-apt 에너지 관측이 대표하는 범위(아파트)가 격자 주택의 얼마인지 볼 때 씁니다.`,
    formula: '아파트(ho_gb_003) ÷ 주택 유형별 합 × 100',
    basis: (p) => sgisBasis(p, null), source: SGIS_SOURCE,
  },
  {
    key: 'completeness', label: '에너지 관측 완전성', unit: '%', group: '데이터 품질', ramp: 'gain', digits: 0,
    value: (p) => (p.electricity_months || p.gas_months ? n(p.completeness) : null), breaks: [25, 50, 75, 100],
    definition: '전력 12개월과 가스 12개월 중 관측이 있는 달의 비율입니다. 관측이 전혀 없는 격자는 결측(회색)으로 둡니다.',
    formula: '(전력 관측 월 + 가스 관측 월) ÷ 24 × 100',
    basis: (p) => `전력 ${p.electricity_months}/12개월 · 가스 ${p.gas_months}/12개월`,
    source: '에너지 관측 월 수',
  },
];

export { USE_COLORS, USE_NAME, USE_ORDER, ZONE_NAME } from './labels';

/** 결측 격자의 바탕색. 그 위에 해치 패턴 레이어를 겹친다(램프 최저색과 구분). */
export const MISSING_FILL = TOKENS['prov-missing-bg'];

export interface MetricClass { color: string; from: number; to: number; count: number }
export interface Classification { classes: MetricClass[]; lowerBounds: number[]; valued: number; missing: number; min: number | null; max: number | null }

/** Lower bounds for classes 2..k from quantiles of the values (distinct, increasing). */
export function quantileBounds(values: number[], classes = 5): number[] {
  const sorted = [...values].sort((a, b) => a - b);
  if (sorted.length < 2) return [];
  const bounds: number[] = [];
  for (let i = 1; i < classes; i++) {
    const q = sorted[Math.min(sorted.length - 1, Math.floor((i * sorted.length) / classes))];
    if (q > sorted[0] && (bounds.length === 0 || q > bounds[bounds.length - 1])) bounds.push(nice(q));
  }
  return [...new Set(bounds)].filter((b) => b > sorted[0]);
}

/** Two significant digits so class bounds read cleanly (1,234 → 1,200; 0.456 → 0.46). */
function nice(value: number): number {
  return value === 0 ? 0 : Number(value.toPrecision(2));
}

/** Classes for the legend and the map. Values equal to a lower bound fall in the upper class. */
export function classify(values: Array<number | null>, fixed?: number[], ramp: RampName = 'seq'): Classification {
  const valid = values.filter((v): v is number => v !== null && Number.isFinite(v));
  const missing = values.length - valid.length;
  if (!valid.length) return { classes: [], lowerBounds: [], valued: 0, missing, min: null, max: null };
  const min = Math.min(...valid), max = Math.max(...valid);
  const lowerBounds = (fixed ?? quantileBounds(valid)).filter((b) => b > min || fixed !== undefined);
  const colors = pickColors(lowerBounds.length + 1, RAMPS[ramp]);
  const edges = [min, ...lowerBounds];
  const classes = edges.map((from, i) => ({ color: colors[i], from: i === 0 ? min : from, to: i < lowerBounds.length ? lowerBounds[i] : max, count: 0 }));
  for (const value of valid) classes[classIndex(value, lowerBounds)].count += 1;
  return { classes, lowerBounds, valued: valid.length, missing, min, max };
}

export function classIndex(value: number, lowerBounds: number[]): number {
  let index = 0;
  for (const bound of lowerBounds) if (value >= bound) index += 1;
  return index;
}

function pickColors(count: number, ramp: string[]): string[] {
  if (count >= ramp.length) return ramp.slice(0, count);
  if (count === 1) return [ramp[3]];
  const step = (ramp.length - 1) / (count - 1);
  return Array.from({ length: count }, (_, i) => ramp[Math.round(i * step)]);
}

/** MapLibre fill color: explicit missing branch (hatch layer drawn on top), then a step ramp on the class bounds. */
export function stepColor(property: string, classification: Classification): unknown[] {
  const colors = classification.classes.map((c) => c.color);
  if (!colors.length) return ['case', ['==', ['get', property], null], MISSING_FILL, MISSING_FILL];
  // 값 있는 격자가 한 구간뿐이면 경계가 없다. MapLibre step은 경계가 1개 이상 필요하므로 단색으로 칠한다.
  if (!classification.lowerBounds.length) return ['case', ['==', ['get', property], null], MISSING_FILL, colors[0]];
  const step: unknown[] = ['step', ['to-number', ['get', property]], colors[0]];
  classification.lowerBounds.forEach((bound, i) => step.push(bound, colors[i + 1]));
  return ['case', ['==', ['get', property], null], MISSING_FILL, step];
}

/** Features with derived metric values stored under their metric key (e.g. tCO₂eq). */
export function withMetricValues(collection: GeoJSON.FeatureCollection<GeoJSON.Geometry, GridProps>): GeoJSON.FeatureCollection<GeoJSON.Geometry, GridProps> {
  return {
    ...collection,
    features: collection.features.map((feature) => {
      const props = { ...(feature.properties as GridProps) };
      for (const metric of METRICS) props[metric.key] = metric.value(props);
      return { ...feature, properties: props };
    }),
  };
}

export function rangeLabel(item: MetricClass, digits: number, last: boolean): string {
  const f = (v: number) => formatMetric(v, '', digits);
  if (item.from === item.to) return f(item.from);
  if (item.to < item.from) return `${f(item.from)} 이상`;
  return last ? `${f(item.from)} ~ ${f(item.to)}` : `${f(item.from)} ~ ${f(item.to)} 미만`;
}
