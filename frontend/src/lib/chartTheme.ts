import type { EChartsOption } from 'echarts';
import { FONT_STACK, POPOVER_SHADOW, TOKENS } from '../theme/palette';

/**
 * 차트 규칙 (DESIGN.md 5): 격자선 --line, 축 글자 12px --ink-3, 주 계열 1.5px.
 * 근거 유형은 선 모양으로: 실측·계산 실선, 추정 점선(4 3), 시나리오 짧은 점선(1 3).
 * 결측 월은 선을 끊고(connectNulls: false) 그 구간에 옅은 해치 띠 + "자료 없음".
 */
export const SERIES = { electricity: TOKENS['series-electricity'], gas: TOKENS['series-gas'], temperature: TOKENS.primary, neutral: TOKENS['ink-2'] };
export type LineStyleKind = 'solid' | 'estimated' | 'scenario';
const DASH: Record<LineStyleKind, 'solid' | number[]> = { solid: 'solid', estimated: [4, 3], scenario: [1, 3] };

export function baseChart(overrides: EChartsOption = {}): EChartsOption {
  return {
    textStyle: { fontFamily: FONT_STACK, color: TOKENS['ink-2'] },
    animation: false,
    grid: { left: 64, right: 20, top: 40, bottom: 30, containLabel: false },
    legend: { top: 0, right: 0, icon: 'rect', itemWidth: 14, itemHeight: 2, textStyle: { color: TOKENS['ink-2'], fontSize: 12 } },
    tooltip: { trigger: 'axis', axisPointer: { type: 'line', lineStyle: { color: TOKENS['line-strong'] } }, backgroundColor: TOKENS.surface, borderColor: TOKENS.line, borderWidth: 1, padding: [6, 10], textStyle: { color: TOKENS.ink, fontSize: 12 }, extraCssText: `border-radius:2px;box-shadow:${POPOVER_SHADOW};` },
    xAxis: { type: 'category', axisLine: { lineStyle: { color: TOKENS['line-strong'] } }, axisTick: { show: false }, axisLabel: { color: TOKENS['ink-3'], fontSize: 12 } },
    yAxis: { type: 'value', nameTextStyle: { color: TOKENS['ink-3'], fontSize: 12, align: 'right' }, splitLine: { lineStyle: { color: TOKENS.line } }, axisLabel: { color: TOKENS['ink-3'], fontSize: 12 } },
    ...overrides,
  };
}

export function lineSeries(name: string, data: Array<number | null>, color: string, kind: LineStyleKind = 'solid') {
  return { name, type: 'line' as const, data, smooth: false, symbol: 'circle', symbolSize: 6, showSymbol: true, connectNulls: false, lineStyle: { width: 1.5, color, type: DASH[kind] }, itemStyle: { color, borderColor: TOKENS.surface, borderWidth: 1 } };
}

/** ECharts pattern fill for missing bands (browser canvas); falls back to the flat missing background. */
export function hatchFill(): string | { image: HTMLCanvasElement; repeat: 'repeat' } {
  if (typeof document === 'undefined') return TOKENS['prov-missing-bg'];
  const canvas = document.createElement('canvas');
  const size = 8; canvas.width = size; canvas.height = size;
  const ctx = canvas.getContext?.('2d');
  if (!ctx) return TOKENS['prov-missing-bg'];
  ctx.fillStyle = TOKENS['prov-missing-bg']; ctx.fillRect(0, 0, size, size);
  ctx.strokeStyle = TOKENS.hatch; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(0, size); ctx.lineTo(size, 0); ctx.moveTo(-2, 2); ctx.lineTo(2, -2); ctx.moveTo(size - 2, size + 2); ctx.lineTo(size + 2, size - 2); ctx.stroke();
  return { image: canvas, repeat: 'repeat' };
}

/** Category indices where every series is missing, merged into runs (for the hatch band). */
export function missingRuns(series: Array<Array<number | null | undefined>>, length: number): Array<[number, number]> {
  const runs: Array<[number, number]> = [];
  for (let i = 0; i < length; i++) {
    const missing = series.every((values) => values[i] === null || values[i] === undefined);
    if (!missing) continue;
    const last = runs[runs.length - 1];
    if (last && last[1] === i - 1) last[1] = i; else runs.push([i, i]);
  }
  return runs;
}

/** markArea for missing months: pale hatch band labelled "자료 없음" (not drawn as zero). */
export function missingBands(categories: string[], series: Array<Array<number | null | undefined>>) {
  const runs = missingRuns(series, categories.length);
  if (!runs.length) return undefined;
  return {
    silent: true,
    itemStyle: { color: hatchFill() as never, opacity: 1 },
    label: { show: true, position: 'insideTop' as const, color: TOKENS['ink-2'], fontSize: 12, backgroundColor: TOKENS['prov-missing-bg'], padding: [1, 3], formatter: '자료 없음' },
    data: runs.map(([a, b]) => [{ xAxis: categories[a] }, { xAxis: categories[b] }]) as never,
  };
}

export const compactAxis = (value: number) => (Math.abs(value) >= 1e8 ? `${value / 1e8}억` : Math.abs(value) >= 1e4 ? `${value / 1e4}만` : String(value));

/** Twelve calendar months of a year, with values looked up by use_ym (YYYYMM); absent months stay null. */
export function monthsOf(year: number, rows: Array<Record<string, unknown>>, key: string): Array<number | null> {
  const byMonth = new Map(rows.map((row) => [String(row.use_ym ?? '').replace('-', ''), row[key]]));
  return Array.from({ length: 12 }, (_, i) => { const value = byMonth.get(`${year}${String(i + 1).padStart(2, '0')}`); return typeof value === 'number' && Number.isFinite(value) ? value : null; });
}
export const MONTH_LABELS = Array.from({ length: 12 }, (_, i) => `${i + 1}월`);
