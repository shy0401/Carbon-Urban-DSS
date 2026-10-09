/**
 * 지역 시뮬레이션 시나리오 비교: 지금 조건과 계산 결과를 이 브라우저에 최대 4개까지 저장해 나란히 본다
 * (ArcGIS Urban 시나리오 비교 보고서, One Click LCA 설계안 4개 비교와 같은 쓰임). 값은 저장 순간 엔진이 낸 그대로이며
 * 여기서 다시 계산하지 않는다. 저장소는 브라우저 localStorage라 다른 PC·브라우저와 공유되지 않는다(링크로 다시 열어 재계산).
 */
import { EFFORT_BASIS_LABEL, toTonnes, type AreaAnalysis, type EffortBasis, type MeasuresState } from './area';

export const SCENARIO_STORE_KEY = 'carbon-dss.area-scenarios.v1';
export const MAX_SCENARIOS = 4;

export interface SavedScenario {
  id: string;
  name: string;
  saved_at: string;
  region: string | null;
  area_label: string;
  /** /area?… 링크 (직접 그린 구역은 null). */
  link: string | null;
  inputs: { from: number; to: number; planned_m2: number; removed_m2: number; target_pct: number; basis: EffortBasis; pv_yield: string; measures: MeasuresState };
  results: {
    available: boolean; reason?: string; basis?: EffortBasis; fallback_from?: EffortBasis; baseline_year?: number; baseline_mode?: string;
    baseline_t: number | null; bau_t: number | null; target_t: number | null; need_t: number | null; already_met?: boolean;
    new_only_pct: number | null; all_pct: number | null; offset_kwh: number | null; pv_kw: number | null; intensity: number | null;
    mix_t: number | null; mix_gap_t: number | null; mix_met: boolean | null; rank: string | null;
  };
}

export function loadScenarios(): SavedScenario[] {
  try {
    const raw = window.localStorage.getItem(SCENARIO_STORE_KEY);
    const list = raw ? (JSON.parse(raw) as SavedScenario[]) : [];
    return Array.isArray(list) ? list.slice(0, MAX_SCENARIOS) : [];
  } catch {
    return [];
  }
}

export function storeScenarios(list: SavedScenario[]): boolean {
  try {
    window.localStorage.setItem(SCENARIO_STORE_KEY, JSON.stringify(list.slice(0, MAX_SCENARIOS)));
    return true;
  } catch {
    return false;
  }
}

export function toScenario(analysis: AreaAnalysis, ctx: { name: string; region: string | null; link: string | null; inputs: SavedScenario['inputs']; rank: string | null; now?: Date }): SavedScenario {
  const e = analysis.effort;
  const o = e?.options;
  const mix = e?.mix;
  return {
    id: `${(ctx.now ?? new Date()).getTime()}-${Math.random().toString(36).slice(2, 7)}`,
    name: ctx.name, saved_at: (ctx.now ?? new Date()).toISOString(), region: ctx.region, area_label: analysis.history.area.label, link: ctx.link, inputs: ctx.inputs,
    results: {
      available: Boolean(e?.available), reason: e?.available ? undefined : e?.reason, basis: e?.basis, fallback_from: e?.fallback_from,
      baseline_year: e?.baseline_year, baseline_mode: e?.baseline_mode,
      baseline_t: toTonnes(e?.baseline_kgco2eq), bau_t: toTonnes(e?.bau_kgco2eq), target_t: toTonnes(e?.target_kgco2eq), need_t: toTonnes(e?.required_reduction_kgco2eq),
      already_met: e?.already_met, new_only_pct: o?.new_only_efficiency_pct ?? null, all_pct: o?.all_buildings_efficiency_pct ?? null,
      offset_kwh: o?.offset_kwh_per_year ?? null, pv_kw: o?.pv_capacity_kw ?? null, intensity: e?.intensity_kwh_per_m2 ?? null,
      mix_t: mix ? mix.total_kgco2eq / 1000 : null, mix_gap_t: mix ? mix.gap_kgco2eq / 1000 : null, mix_met: mix ? mix.met : null, rank: ctx.rank,
    },
  };
}

/** One row per measure, one column per scenario (the shape the comparison table and the CSV share). */
export function comparisonRows(list: SavedScenario[]): Array<{ label: string; values: string[] }> {
  const n = (v: number | null | undefined, digits = 1, unit = '') => (v === null || v === undefined ? '자료 없음' : `${v.toLocaleString('ko-KR', { maximumFractionDigits: digits })}${unit}`);
  const row = (label: string, pick: (s: SavedScenario) => string) => ({ label, values: list.map(pick) });
  return [
    row('구역', (s) => s.area_label),
    row('분석 기간', (s) => `${s.inputs.from}~${s.inputs.to}`),
    row('계획 연면적 (m²)', (s) => n(s.inputs.planned_m2, 0)),
    row('철거 연면적 (m²)', (s) => n(s.inputs.removed_m2, 0)),
    row('목표 감축률 (%)', (s) => n(s.inputs.target_pct, 1)),
    row('기준 건물', (s) => (s.results.basis ? EFFORT_BASIS_LABEL[s.results.basis] + (s.results.fallback_from ? ' (자동 전환)' : '') : '—')),
    row('기준 연도', (s) => (s.results.baseline_year ? `${s.results.baseline_year} ${s.results.baseline_mode === 'OBSERVED' ? '관측' : '추정'}` : '—')),
    row('기준 배출 (tCO₂eq/년)', (s) => n(s.results.baseline_t)),
    row('계획 반영 배출 (tCO₂eq/년)', (s) => n(s.results.bau_t)),
    row('목표 배출 (tCO₂eq/년)', (s) => n(s.results.target_t)),
    row('필요 감축량 (tCO₂eq/년)', (s) => (!s.results.available ? s.results.reason ?? '계산 근거 없음' : s.results.already_met ? '추가 감축 불필요' : n(s.results.need_t))),
    row('신축만 개선 시 절감률 (%)', (s) => n(s.results.new_only_pct)),
    row('전체 건물 개선 시 절감률 (%)', (s) => n(s.results.all_pct)),
    row('태양광 설비 (kW)', (s) => n(s.results.pv_kw)),
    row('감축 수단 조합 (tCO₂eq/년)', (s) => (s.results.mix_t === null ? '입력 없음' : `${n(s.results.mix_t)} · ${s.results.mix_met ? '목표 달성' : `${n(s.results.mix_gap_t)} 부족`}`)),
    row('전력 원단위 (kWh/m²·년)', (s) => n(s.results.intensity, 2)),
    row('같은 시·군 행정동 비교', (s) => s.results.rank ?? '—'),
  ];
}

/** CSV for Excel (UTF-8 BOM so Korean opens correctly). */
export function scenariosCsv(list: SavedScenario[]): string {
  const cell = (v: string) => (/[",\n]/.test(v) ? `"${v.replace(/"/g, '""')}"` : v);
  const lines = [['항목', ...list.map((s) => s.name)], ...comparisonRows(list).map((r) => [r.label, ...r.values]), ['저장 시각', ...list.map((s) => s.saved_at)], ['링크', ...list.map((s) => s.link ?? '직접 그린 구역(링크 없음)')]];
  return '﻿' + lines.map((l) => l.map(cell).join(',')).join('\r\n') + '\r\n';
}
