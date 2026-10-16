import { classify, MISSING_FILL, type Classification } from './mapMetrics';
import { formatMetric } from './format';

/** 국토통계지도 100m 격자 (팀 수집, 국외 반출 금지): 지도 레이어와 격자 상세의 25칸 패널이 같은 정의를 쓴다. */

export interface Grid100Props {
  id: string; x: number; y: number; grid500: string;
  population: number | null; population_status: 'observed' | 'masked' | 'empty';
  building_count: number | null; floor_area_m2: number | null; approval_year: number | null; zone_class: string | null;
}
export interface Grid100Meta { source: string; years: number[]; year: number | null; cells: number; returned: number; truncated: boolean; reason: string | null; restricted?: boolean }
export interface Grid100Summary { cells_with_data: number; population_sum: number | null; population_cells: number; masked_cells: number; buildings_sum: number | null; floor_area_sum: number | null }
export interface Grid100Response { type: 'FeatureCollection'; features: Array<GeoJSON.Feature<GeoJSON.Polygon, Grid100Props>>; meta: Grid100Meta; summary: Grid100Summary | null }

export type Grid100Key = 'population' | 'building_count' | 'floor_area_m2' | 'approval_year';
export interface Grid100Metric { key: Grid100Key; label: string; unit: string; digits: number; breaks: number[]; note: string }

/** 100m 칸 하나(1ha) 기준의 고정 경계: 화면을 옮겨도 같은 값은 같은 색. 색 띠가 5색이라 경계는 4개(구간 5개)까지. */
export const GRID100_METRICS: Grid100Metric[] = [
  { key: 'population', label: '인구', unit: '명', digits: 0, breaks: [20, 50, 100, 250], note: '공개값은 6명 이상입니다. 1~5명 칸은 비공개라 빗금으로, 값이 비어 있는 칸은 칠하지 않습니다(0 아님).' },
  { key: 'building_count', label: '건물 수', unit: '동', digits: 0, breaks: [2, 5, 10, 20], note: '국토통계지도 건물 격자 통계의 건축물 수입니다. 건물이 없는 칸은 값이 비어 있습니다.' },
  { key: 'floor_area_m2', label: '추정 연면적', unit: 'm²', digits: 0, breaks: [2000, 5000, 15000, 40000], note: '국토통계지도의 칸 평균 연면적 × 건물 수로 낸 추정입니다(팀 계산).' },
  { key: 'approval_year', label: '평균 사용승인연도', unit: '년', digits: 0, breaks: [1980, 1990, 2000, 2010], note: '칸 안 건물의 평균 사용승인연도입니다. 색이 진할수록 최근 건물입니다.' },
];

export const ZONE_CLASS_NAME: Record<string, string> = {
  residential: '주거', commercial: '상업', industrial: '공업', green: '녹지', management: '관리', agricultural: '농림', conservation: '자연환경보전', other: '기타', none: '용도지역 없음',
};

export const GRID100_MIN_ZOOM = 13;

export function grid100Metric(key: Grid100Key): Grid100Metric { return GRID100_METRICS.find((m) => m.key === key) ?? GRID100_METRICS[0]; }

export function grid100Classify(features: Array<{ properties: Grid100Props }>, metric: Grid100Metric): Classification {
  return classify(features.map((f) => f.properties[metric.key]), metric.breaks, 'seq');
}

/** One value as text: years without a thousands separator ('1995년'), others with their unit. */
export function grid100Value(value: number | null, metric: Grid100Metric): string {
  if (value === null || !Number.isFinite(value)) return '값 없음';
  return metric.key === 'approval_year' ? `${Math.round(value)}년` : formatMetric(value, metric.unit, metric.digits);
}

/** Legend text of class i from the fixed bounds (not the data range), so an empty class still reads right. */
export function grid100ClassLabel(classification: Classification, i: number, metric: Grid100Metric): string {
  const b = classification.lowerBounds;
  const f = (v: number) => (metric.key === 'approval_year' ? `${v}년` : formatMetric(v, '', metric.digits));
  if (!b.length) return classification.min === null ? '' : f(classification.min);
  if (i === 0) return metric.key === 'approval_year' ? `${b[0]}년 이전` : `${f(b[0])} 미만`;
  if (i >= b.length) return `${f(b[b.length - 1])} 이상`;
  return `${f(b[i - 1])} ~ ${f(b[i])} 미만`;
}

/** MapLibre fill color by fixed class bounds; a cell without the value is transparent (masked population gets the hatch layer). */
export function grid100Color(metric: Grid100Metric, classification: Classification): unknown[] {
  const colors = classification.classes.map((c) => c.color);
  if (!colors.length) return ['rgba', 0, 0, 0, 0];
  return ['case', ['==', ['get', metric.key], null], ['rgba', 0, 0, 0, 0], ['step', ['to-number', ['get', metric.key]], colors[0], ...classification.lowerBounds.flatMap((b, i) => [b, colors[i + 1]])]];
}

/** Color of one value with the same classes (the 5×5 panel draws with CSS, not MapLibre). */
export function grid100Fill(value: number | null, classification: Classification): string | null {
  if (value === null || !classification.classes.length) return null;
  let index = 0; for (const b of classification.lowerBounds) if (value >= b) index += 1;
  return classification.classes[index]?.color ?? MISSING_FILL;
}

export function populationText(p: Pick<Grid100Props, 'population' | 'population_status'>): string {
  if (p.population_status === 'masked') return '1~5명 (비공개)';
  if (p.population === null) return '값 없음 (0인지 미확인)';
  return formatMetric(p.population, '명', 0);
}

export function grid100Lines(p: Grid100Props): Array<[string, string]> {
  return [
    ['인구', populationText(p)],
    ['건물 수', p.building_count === null ? '값 없음' : formatMetric(p.building_count, '동', 0)],
    ['추정 연면적', p.floor_area_m2 === null ? '값 없음' : formatMetric(p.floor_area_m2, 'm²', 0)],
    ['평균 사용승인', p.approval_year === null ? '값 없음' : `${Math.round(p.approval_year)}년`],
    ['용도지역', p.zone_class ? ZONE_CLASS_NAME[p.zone_class] ?? p.zone_class : '값 없음'],
  ];
}

function esc(value: unknown): string { return String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] ?? c); }

export function grid100Tooltip(p: Grid100Props, year: number | null): string {
  return `<div class="map-tip"><strong>100m 칸 (국토통계지도${year ? ` ${year}년` : ''})</strong>${grid100Lines(p).map(([k, v]) => `<span>${esc(k)} <b>${esc(v)}</b></span>`).join('')}</div>`;
}

/** Why the layer cannot be shown here, or null when it can. */
export function grid100Unavailable(meta: Grid100Meta | { restricted: true } | null | undefined): string | null {
  if (!meta) return '100m 자료 확인 중이거나 없습니다';
  if ('restricted' in meta && meta.restricted) return '이용 조건(국외 반출 금지)상 공개 주소에서는 볼 수 없습니다';
  const m = meta as Grid100Meta;
  if (!m.years?.length || !m.cells) return m.reason ?? '이 지역에는 100m 자료가 없습니다';
  return null;
}
