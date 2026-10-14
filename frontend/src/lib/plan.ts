import type { EChartsOption } from 'echarts';
import { baseChart, compactAxis, lineSeries, missingBands } from './chartTheme';
import { formatMetric } from './format';
import { TOKENS } from '../theme/palette';
import type { ScenarioResult, ScenarioSeries } from '../types';

/** What a reader needs from one computed plan: its yearly numbers, the reference plan and the savings between them. */

export function tonnes(kg: number | null | undefined, digits = 1): string {
  if (typeof kg !== 'number' || !Number.isFinite(kg)) return '자료 없음';
  return `${new Intl.NumberFormat('ko-KR', { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(kg / 1000)} tCO₂eq`;
}

/** '−27.7%' for savings, '+3.0%' when the plan uses more; the sign follows what the reader expects of a 절감률. */
export function savingsText(pct: number | null | undefined): string {
  if (typeof pct !== 'number' || !Number.isFinite(pct)) return '자료 없음';
  return `${pct > 0 ? '−' : pct < 0 ? '+' : ''}${Math.abs(pct).toFixed(1)}%`;
}

export function annualSide(result: ScenarioResult, side: 'scenario' | 'reference' | 'current'): ScenarioSeries | null {
  const value = result.annual?.[side];
  return value && typeof value === 'object' ? (value as ScenarioSeries) : null;
}

export function gasCarbon(series: ScenarioSeries | null): number | null {
  const total = series?.carbon_kg; const electricity = series?.electricity_carbon_kg;
  return typeof total === 'number' && typeof electricity === 'number' ? total - electricity : null;
}

export function hasAnnual(result: ScenarioResult): boolean {
  const plan = annualSide(result, 'scenario');
  return !!plan && Object.values(plan).some((v) => typeof v === 'number');
}

/** The calculation in one sentence, with the intensity and factors it used. */
export function methodText(result: ScenarioResult, factors?: Record<string, { factor?: number | null; assumed?: boolean }> | null): string {
  const bi = result.baseline_intensity;
  const parts = [bi?.electricity_kwh_per_m2 != null ? `전력 ${formatMetric(bi.electricity_kwh_per_m2, 'kWh/m²·년', 1)}` : null, bi?.gas_kwh_per_m2 != null ? `가스 ${formatMetric(bi.gas_kwh_per_m2, 'kWh/m²·년', 1)}` : null].filter(Boolean);
  const intensity = parts.length ? parts.join(', ') : '격자 관측 원단위';
  const e = factors?.ELECTRICITY; const g = factors?.GAS;
  const factorText = factors ? ` 배출계수는 전력 ${e?.factor ?? '미등록'} kgCO₂eq/kWh(${e && !e.assumed ? 'GIR 승인' : '확인 필요'}), 가스 ${g?.factor ?? '미등록'} kgCO₂eq/kWh(${g?.assumed ? '가정' : '등록'})입니다.` : '';
  return `격자 관측 원단위(${intensity}) × 계획 연면적 × 효율 계수로 계산하고, 전력은 (1 − 태양광 전력 대체율)을 곱합니다. 기준안은 같은 연면적을 효율 계수 1.0·태양광 0으로 지을 때입니다.${factorText}`;
}

function monthLabel(value: unknown) { const text = String(value ?? ''); const month = Number(text.replace('-', '').slice(-2)); return month >= 1 && month <= 12 ? `${month}월` : text; }

function pick(row: Record<string, unknown>, side: string, key: string): number | null {
  const nested = row[side];
  const value = nested && typeof nested === 'object' ? (nested as Record<string, unknown>)[key] : null;
  return typeof value === 'number' ? value : null;
}

/** Monthly chart: the plan (solid) against its reference plan (dashed), one axis, missing months left empty. */
export function planChartOption(result: ScenarioResult, label = '계획안', color = TOKENS['plan-a']): { option: EChartsOption; unit: string } | null {
  return plansChartOption([{ result, label, color }]);
}

/** Several plans of one site on one axis (A·B·C solid) with the first plan's reference plan dashed. */
export function plansChartOption(plans: Array<{ result: ScenarioResult; label: string; color: string }>): { option: EChartsOption; unit: string } | null {
  const first = plans[0]; if (!first) return null;
  const rows = Array.isArray(first.result.monthly) ? first.result.monthly : [];
  if (!rows.length) return null;
  const key = rows.some((row) => pick(row, 'scenario', 'carbon_kg') !== null) ? 'carbon_kg' : 'electricity_kwh';
  const unit = key === 'carbon_kg' ? 'kgCO₂eq' : 'kWh';
  const labels = rows.map((row) => monthLabel(row.use_ym ?? row.month));
  const plan = rows.map((row) => pick(row, 'scenario', key));
  const reference = rows.map((row) => pick(row, 'reference', key));
  if (plan.every((v) => v === null)) return null;
  const base = baseChart();
  const series = plans.map((p, i) => lineSeries(p.label, (Array.isArray(p.result.monthly) ? p.result.monthly : []).map((row) => pick(row, 'scenario', key)), p.color, i === 0 ? 'solid' : 'solid'));
  if (reference.some((v) => v !== null)) series.push(lineSeries(plans.length > 1 ? `기준안 (${first.label} 연면적, 효율 1.0·태양광 0)` : '기준안 (효율 1.0·태양광 0)', reference, TOKENS['ink-3'], 'estimated'));
  return {
    unit,
    option: baseChart({
      legend: { show: true, top: 0, right: 8, icon: 'roundRect', itemWidth: 14, itemHeight: 3, textStyle: { color: TOKENS['ink-2'] } },
      grid: { left: 64, right: 20, top: 44, bottom: 30 },
      tooltip: { ...(base.tooltip as object), valueFormatter: (value: unknown) => (typeof value === 'number' ? formatMetric(value, unit, 0) : '자료 없음') },
      xAxis: { ...(base.xAxis as object), data: labels },
      yAxis: { ...(base.yAxis as object), name: unit, axisLabel: { ...((base.yAxis as { axisLabel?: object }).axisLabel ?? {}), formatter: compactAxis } },
      series: series.map((s, i) => (i === 0 ? { ...s, markArea: missingBands(labels, [plan]) } : s)),
    }),
  };
}
