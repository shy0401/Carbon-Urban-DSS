import { classify, type Classification } from './mapMetrics';
import { formatMetric } from './format';
import { TOKENS } from '../theme/palette';

/** 선도소프트가 준 탄소공간지도 100m 건물 전기 배출(tCO₂eq/년). 지도 레이어와 격자 상세 25칸이 같은 정의를 쓴다. */

export interface KcsmProps {
  id: string; x: number; y: number; grid500: string;
  /** 연간 건물 전기 배출, tCO₂eq (제공 값). */
  elec_t: number | null;
  /** value: 0보다 큼, zero: 제공값 0(건물 없음인지 미연계인지 확인 필요), missing: 값 없음. */
  status: 'value' | 'zero' | 'missing';
  prev_year: number | null; prev_t: number | null; change_pct: number | null;
  /** 앞 해 100 tCO₂eq 이상이던 칸이 절반 아래로 줄어 원자료 누락이 의심됨(표시만). */
  drop: boolean; drop_from_t: number | null;
  monthly?: Array<number | null>;
}
export interface KcsmMeta { source: string | null; unit?: string; years: number[]; year: number | null; cells: number; returned: number; truncated: boolean; reason: string | null }
export interface KcsmSummary { cells: number; value_cells: number; zero_cells: number; total_t: number | null; prev_total_t: number | null; drop_cells: number; monthly: Array<number | null> }
export interface KcsmResponse { type: 'FeatureCollection'; features: Array<GeoJSON.Feature<GeoJSON.Polygon, KcsmProps>>; meta: KcsmMeta; summary: KcsmSummary | null }

/** 1ha 칸 기준 고정 경계(tCO₂eq/년): 전주 2024년 값 있는 칸의 중앙값 약 50 t, 상위 10% 약 440 t. 색 띠가 5색이라 경계는 4개. */
export const KCSM_BREAKS = [10, 50, 200, 1000];
export const KCSM_MIN_ZOOM = 13;
export const KCSM_ZERO_FILL = TOKENS['surface-sunk'] ?? '#eef0f3';

export function kcsmClassify(features: Array<{ properties: KcsmProps }>): Classification {
  return classify(features.map((f) => (f.properties.elec_t && f.properties.elec_t > 0 ? f.properties.elec_t : null)), KCSM_BREAKS, 'seq');
}

/** MapLibre fill: 0(제공값)은 옅은 회색, 값이 없으면 투명, 나머지는 고정 구간. */
export function kcsmColor(classification: Classification): unknown[] {
  const colors = classification.classes.map((c) => c.color);
  const step = colors.length ? ['step', ['to-number', ['get', 'elec_t']], colors[0], ...classification.lowerBounds.flatMap((b, i) => [b, colors[i + 1]])] : KCSM_ZERO_FILL;
  return ['case', ['==', ['get', 'status'], 'zero'], KCSM_ZERO_FILL, ['==', ['get', 'status'], 'missing'], ['rgba', 0, 0, 0, 0], step];
}

export function kcsmFill(p: KcsmProps | null, classification: Classification): string | null {
  if (!p || p.elec_t === null) return null;
  if (p.elec_t === 0) return KCSM_ZERO_FILL;
  if (!classification.classes.length) return null;
  let index = 0; for (const b of classification.lowerBounds) if (p.elec_t >= b) index += 1;
  return classification.classes[index]?.color ?? null;
}

export function kcsmClassLabel(classification: Classification, i: number): string {
  const b = classification.lowerBounds;
  const f = (v: number) => formatMetric(v, '', 0);
  if (!b.length) return classification.min === null ? '' : f(classification.min);
  if (i === 0) return `${f(b[0])} 미만`;
  if (i >= b.length) return `${f(b[b.length - 1])} 이상`;
  return `${f(b[i - 1])} ~ ${f(b[i])} 미만`;
}

export function kcsmValueText(p: Pick<KcsmProps, 'elec_t'>): string {
  if (p.elec_t === null) return '값 없음';
  if (p.elec_t === 0) return '0 (제공값, 건물 없음인지 확인 필요)';
  return formatMetric(p.elec_t, 'tCO₂eq/년', p.elec_t < 10 ? 2 : 1);
}

export function kcsmLines(p: KcsmProps, year: number | null): Array<[string, string]> {
  const out: Array<[string, string]> = [[`${year ?? ''}년 전기 배출`.trim(), kcsmValueText(p)]];
  if (p.prev_year) out.push([`${p.prev_year}년`, p.prev_t === null ? '값 없음' : formatMetric(p.prev_t, 'tCO₂eq', p.prev_t < 10 ? 2 : 1) + (p.change_pct === null ? '' : ` (${p.change_pct > 0 ? '+' : ''}${p.change_pct.toFixed(1)}%)`)]);
  if (p.drop) out.push(['표시', `급감 (앞 해 ${formatMetric(p.drop_from_t, 't', 1)}) · 원자료 누락 의심`]);
  return out;
}

/** Feature properties as MapLibre hands them back (null may be dropped, values may come back as strings). */
export function kcsmFromFeature(raw: Record<string, unknown>): KcsmProps {
  const n = (v: unknown) => (v === null || v === undefined || v === '' || v === 'null' ? null : Number.isFinite(Number(v)) ? Number(v) : null);
  const elec = n(raw.elec_t);
  return {
    id: String(raw.id ?? ''), x: Number(raw.x), y: Number(raw.y), grid500: String(raw.grid500 ?? ''), elec_t: elec,
    status: raw.status === 'zero' || raw.status === 'value' || raw.status === 'missing' ? raw.status : elec === null ? 'missing' : elec === 0 ? 'zero' : 'value',
    prev_year: n(raw.prev_year), prev_t: n(raw.prev_t), change_pct: n(raw.change_pct), drop: String(raw.drop) === 'true', drop_from_t: n(raw.drop_from_t),
  };
}

function esc(value: unknown): string { return String(value ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] ?? c); }

export function kcsmTooltip(p: KcsmProps, year: number | null): string {
  return `<div class="map-tip"><strong>100m 칸 전기 배출 (탄소공간지도, 선도소프트)</strong>${kcsmLines(p, year).map(([k, v]) => `<span>${esc(k)} <b>${esc(v)}</b></span>`).join('')}</div>`;
}

/** Why the layer cannot be shown here, or null when it can. */
export function kcsmUnavailable(meta: KcsmMeta | { restricted: true } | null | undefined): string | null {
  if (!meta) return '100m 전력 배출 자료가 없습니다';
  if ('restricted' in meta && meta.restricted) return '이용 조건 확인 전이라 공개 주소에서는 볼 수 없습니다';
  const m = meta as KcsmMeta;
  if (!m.years?.length || !m.cells) return m.reason ?? '이 지역에는 100m 전력 배출 자료가 없습니다';
  return null;
}
