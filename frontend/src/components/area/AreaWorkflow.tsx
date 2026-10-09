/**
 * 지역 시뮬레이션의 업무 흐름 부품 (2026-10 사용성 개선).
 * - 결과 요약 막대: 단계 이동 + 핵심 지표(엔진 값 그대로)
 * - 감축 수단 조합: 신축·기존 건물 절감률과 태양광을 함께 넣어 필요 감축량을 채우는지 확인 (도시·군기본계획 방식)
 * - 같은 시·군·구 행정동 비교: 원단위 분포 속 위치 (ENERGY STAR·서울 건물에너지 등급처럼 동종 비교, 단 등급 아님)
 * - 시나리오 비교: 최대 4개 안을 나란히, CSV(엑셀)로 내보내기
 * 숫자는 모두 서버 계산 엔진이 낸 값이며 여기서는 고르거나 단위(kg→t)만 바꾼다.
 */
import { Download, ExternalLink, Save, Sun, Trash2 } from 'lucide-react';
import type { ReactNode } from 'react';
import { benchmarkPosition, EFFORT_BASIS_LABEL, NO_MEASURES, toTonnes, type AreaAnalysis, type Benchmark, type EffortResult, type MeasuresState } from '../../lib/area';
import { comparisonRows, MAX_SCENARIOS, scenariosCsv, type SavedScenario } from '../../lib/areaScenarios';
import { formatMetric } from '../../lib/format';

export const AREA_STEPS = [
  { id: 'area-step-area', label: '구역 고르기' },
  { id: 'area-step-plan', label: '계획·목표' },
  { id: 'area-step-measures', label: '감축 수단' },
  { id: 'area-step-compare', label: '시나리오 비교' },
  { id: 'area-step-report', label: '보고서' },
] as const;

const t1 = (kg: number | null | undefined) => formatMetric(toTonnes(kg), 't', 1);

function go(id: string) {
  const el = typeof document === 'undefined' ? null : document.getElementById(id);
  if (el && typeof el.scrollIntoView === 'function') el.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

function Kpi({ label, value, sub, tone }: { label: string; value: ReactNode; sub?: ReactNode; tone?: 'good' | 'warn' | 'bad' }) {
  return <div className={tone ? `is-${tone}` : undefined}><dt>{label}</dt><dd>{value}{sub && <small>{sub}</small>}</dd></div>;
}

/** 한 줄 위치 문장: '전주 행정동 30곳 중 낮은 쪽부터 12번째'. 같은 기준·같은 연도일 때만. */
export function benchmarkText(bench: Benchmark | null | undefined, effort: EffortResult | null | undefined) {
  if (!bench || !effort?.available || effort.baseline_mode !== 'OBSERVED' || bench.basis !== effort.basis) return null;
  const pos = benchmarkPosition(bench, effort.baseline_year, effort.intensity_kwh_per_m2);
  if (!pos) return null;
  return { pos, text: `${pos.rank}/${pos.count}번째`, detail: `${bench.reference_year}년 ${bench.basis_label} 원단위 낮은 쪽부터${pos.quintile ? ` · 5분위 중 ${pos.quintile}분위` : ''}` };
}

export function AreaSummaryBar({ analysis, running, bench, onSave, saveNote }: { analysis: AreaAnalysis | null; running: boolean; bench: Benchmark | null; onSave: () => void; saveNote?: string | null }) {
  const e = analysis?.effort;
  const ok = Boolean(e?.available);
  const position = benchmarkText(bench, e);
  const mix = e?.mix;
  return <section className="area-summary" aria-label="결과 요약" data-testid="area-summary">
    <nav className="area-steps" aria-label="작업 단계">
      <ol>{AREA_STEPS.map((s, i) => <li key={s.id}><a href={`#${s.id}`} onClick={(event) => { event.preventDefault(); go(s.id); }}><b aria-hidden="true">{i + 1}</b>{s.label}</a></li>)}</ol>
    </nav>
    <dl className="area-kpis" aria-live="polite">
      <Kpi label="구역" value={analysis?.history.area.label ?? '구역을 고르세요'} sub={running ? '계산 중…' : analysis ? `${analysis.history.years[0]}~${analysis.history.years[analysis.history.years.length - 1]}` : undefined} />
      {ok && e ? <>
        <Kpi label="기준 배출" value={t1(e.baseline_kgco2eq)} sub={`${e.baseline_year}년 ${e.baseline_mode === 'OBSERVED' ? '관측' : '추정'} · ${e.basis ? EFFORT_BASIS_LABEL[e.basis] : ''}${e.fallback_from ? ' (자동 전환)' : ''}`} />
        <Kpi label="계획 반영 (대책 없음)" value={t1(e.bau_kgco2eq)} sub={`목표 ${formatMetric(e.target_pct, '%')} 감축선 ${t1(e.target_kgco2eq)}`} />
        <Kpi label="필요 감축량" value={e.already_met ? '불필요' : t1(e.required_reduction_kgco2eq)} sub="연간, 전력 운영탄소" tone={e.already_met ? 'good' : undefined} />
        <Kpi label="감축 수단 조합" value={mix ? t1(mix.total_kgco2eq) : '입력 전'} sub={mix ? (mix.met ? '목표 달성' : `${t1(mix.gap_kgco2eq)} 부족`) : '3단계에서 입력'} tone={mix ? (mix.met ? 'good' : 'warn') : undefined} />
        <Kpi label="같은 시·군 비교" value={position ? position.text : '—'} sub={position ? position.detail : '같은 연도·기준 관측일 때만'} />
      </> : analysis ? <Kpi label="감축 노력" value="계산 근거 없음" sub={e?.reason ?? '목표를 넣으면 계산합니다'} tone="warn" /> : null}
    </dl>
    <div className="area-summary-actions">
      <button type="button" className="button small" onClick={onSave} disabled={!analysis || running}><Save size={14} />시나리오 저장</button>
      {saveNote && <small role="status">{saveNote}</small>}
    </div>
  </section>;
}

export function FallbackNotice({ effort }: { effort: EffortResult | null }) {
  if (!effort?.available || !effort.fallback_from || !effort.basis) return null;
  return <p className="area-fallback" role="note"><b>기준 자동 전환:</b> 요청한 {EFFORT_BASIS_LABEL[effort.fallback_from]} 기준은 {effort.fallback_reason ?? '계산할 근거가 없어'} → {EFFORT_BASIS_LABEL[effort.basis]} 기준으로 계산했습니다.</p>;
}

export function MeasuresPanel({ effort, measures, setMeasures }: { effort: EffortResult | null; measures: MeasuresState; setMeasures: (m: MeasuresState) => void }) {
  const mix = effort?.mix;
  const yieldPerKw = effort?.pv_yield?.kwh_per_kw ?? null;
  const field = (key: keyof MeasuresState, label: string, unit: string, max: number, step: number, hint: string) =>
    <label className="field" key={key}><span>{label}</span><div><input type="number" min={0} max={max} step={step} value={measures[key]} aria-label={label}
      onChange={(ev) => setMeasures({ ...measures, [key]: Math.min(max, Math.max(0, Number(ev.target.value) || 0)) })} /><em>{unit}</em></div><small className="muted">{hint}</small></label>;
  const fillWithPv = () => {
    if (!mix || mix.met || !yieldPerKw || !effort?.factor_kgco2eq_per_kwh) return;
    const extra = Math.ceil((mix.gap_kgco2eq / effort.factor_kgco2eq_per_kwh / yieldPerKw) * 10) / 10;
    setMeasures({ ...measures, pv_kw: Math.round((measures.pv_kw + extra) * 10) / 10 });
  };
  const need = mix?.required_kgco2eq ?? 0;
  const share = (kwh: number | null) => (need > 0 && kwh && effort?.factor_kgco2eq_per_kwh ? Math.min(100, (kwh * effort.factor_kgco2eq_per_kwh / need) * 100) : 0);
  const parts = mix ? [{ key: 'new', label: '신축', value: share(mix.new_kwh) }, { key: 'existing', label: '기존 건물', value: share(mix.existing_kwh) }, { key: 'pv', label: '태양광', value: share(mix.pv_kwh) }] : [];
  let left = 100;
  return <section className="panel area-measures" aria-label="감축 수단 조합">
    <div className="panel-title"><h3>감축 수단 조합</h3><span className="status-tag neutral">수단별 감축량 합산 → 목표 확인</span></div>
    {!effort?.available ? <p className="muted">감축 노력을 계산할 수 있는 구역에서 씁니다.</p> : effort.already_met ? <p className="area-headline good">계획을 반영해도 목표선 아래라 추가 수단이 필요하지 않습니다.</p> : <>
      <div className="field-grid area-measures-form">
        {field('new_efficiency_pct', '신축 건물 전력 절감', '%', 100, 5, `신축 부하 ${formatMetric(effort.new_load_kwh, 'kWh/년')} 기준`)}
        {field('existing_efficiency_pct', '기존 건물 전력 절감', '%', 100, 1, `기준 부하 ${formatMetric(effort.baseline_kwh, 'kWh/년')} − 철거분 기준`)}
        {field('pv_kw', '태양광 설비', 'kW', 1000000, 10, yieldPerKw ? `kW당 ${formatMetric(yieldPerKw, 'kWh/년')} (${effort.pv_yield?.basis === 'USER' ? '입력값' : '지역 추정'})` : '발전량 근거가 없어 합계에서 빠집니다')}
      </div>
      {mix ? <div className="area-mix" data-testid="area-mix">
        <div className="area-mix-bar" role="img" aria-label={`필요 감축량 대비 ${formatMetric(mix.share_pct, '%', 1)}`}>
          {parts.map((p) => { const w = Math.min(left, p.value); left -= w; return w > 0 ? <span key={p.key} className={`seg-${p.key}`} style={{ width: `${w}%` }} title={`${p.label} ${w.toFixed(1)}%`} /> : null; })}
        </div>
        <ul className="area-mix-legend"><li><i className="seg-new" />신축 {formatMetric(mix.new_kwh, 'kWh')}</li><li><i className="seg-existing" />기존 건물 {formatMetric(mix.existing_kwh, 'kWh')}</li><li><i className="seg-pv" />태양광 {mix.pv_counted ? formatMetric(mix.pv_kwh, 'kWh') : '근거 없음'}</li></ul>
        <p className={`area-headline ${mix.met ? 'good' : 'warn'}`} role="status">
          {mix.met ? `조합으로 연간 ${t1(mix.total_kgco2eq)}를 줄여 필요 감축량 ${t1(mix.required_kgco2eq)}를 채웁니다 (여유 ${t1(-mix.gap_kgco2eq)}).`
            : `조합으로 연간 ${t1(mix.total_kgco2eq)}를 줄입니다. 필요 감축량 ${t1(mix.required_kgco2eq)}의 ${formatMetric(mix.share_pct, '%', 1)}로, ${t1(mix.gap_kgco2eq)}가 남습니다.`}
        </p>
      </div> : <p className="muted">값을 넣으면 수단별 감축량을 더해 필요 감축량 {t1(effort.required_reduction_kgco2eq)}와 비교합니다.</p>}
      <div className="area-measures-actions">
        <button type="button" className="button small" onClick={fillWithPv} disabled={!mix || mix.met || !yieldPerKw}><Sun size={14} />남은 양을 태양광으로 채우기</button>
        <button type="button" className="button ghost small" onClick={() => setMeasures(NO_MEASURES)} disabled={measures === NO_MEASURES}>초기화</button>
      </div>
      <p className="muted">도시·군기본계획 수립지침의 탄소중립 계획처럼 수단별 예상 감축량을 더해 목표 달성 여부를 봅니다. 기존 건물 절감은 철거분을 뺀 기준 부하에, 태양광은 kW당 연 발전량에 곱합니다(전력 배출계수 {effort.factor_kgco2eq_per_kwh} kgCO₂eq/kWh).</p>
    </>}
  </section>;
}

export function BenchmarkPanel({ bench, effort, regionName }: { bench: Benchmark | null; effort: EffortResult | null; regionName: string }) {
  if (!bench || !bench.count || bench.min === null || bench.max === null) return null;
  const position = benchmarkText(bench, effort);
  const mine = position ? effort?.intensity_kwh_per_m2 ?? null : null;
  const lo = Math.min(bench.min, mine ?? bench.min); const hi = Math.max(bench.max, mine ?? bench.max);
  const span = hi - lo || 1;
  const x = (v: number) => 12 + ((v - lo) / span) * 576;
  const peers = bench.items.filter((i) => i.year === bench.reference_year && i.kwh_per_m2 !== null);
  return <section className="panel area-benchmark" aria-label="같은 시·군·구 행정동 비교">
    <div className="panel-title"><h3>같은 {regionName} 행정동과 비교</h3><span className="status-tag neutral">{bench.reference_year}년 · {bench.basis_label} · {bench.count}곳</span></div>
    <svg viewBox="0 0 600 64" className="area-benchmark-strip" role="img" aria-label={`행정동 ${bench.count}곳 원단위 ${formatMetric(bench.min, '', 1)}~${formatMetric(bench.max, '', 1)} kWh/m²·년, 중앙값 ${formatMetric(bench.median, '', 1)}${position ? `, 이 구역 ${position.text}` : ''}`}>
      <line x1={12} x2={588} y1={30} y2={30} className="axis" />
      {(bench.quintiles ?? []).map((q) => <line key={q} x1={x(q)} x2={x(q)} y1={20} y2={40} className="tick" />)}
      {bench.median !== null && <line x1={x(bench.median)} x2={x(bench.median)} y1={14} y2={46} className="median" />}
      {peers.map((p) => <circle key={p.code} cx={x(p.kwh_per_m2 as number)} cy={30} r={4.5} className="peer"><title>{`${p.name} ${formatMetric(p.kwh_per_m2, 'kWh/m²', 2)}`}</title></circle>)}
      {mine !== null && <><circle cx={x(mine)} cy={30} r={7} className="mine" /><text x={Math.min(560, Math.max(40, x(mine)))} y={60} textAnchor="middle" className="mine-label">이 구역 {formatMetric(mine, '', 1)}</text></>}
      <text x={12} y={12} className="end">{formatMetric(lo, '', 1)}</text><text x={588} y={12} textAnchor="end" className="end">{formatMetric(hi, '', 1)} kWh/m²·년</text>
    </svg>
    <p className="area-benchmark-text">{position ? <><b>낮은 쪽부터 {position.text}</b> ({position.detail}) · 중앙값 {formatMetric(bench.median, 'kWh/m²·년', 2)}</>
      : <>이 구역은 {effort?.available ? (effort.baseline_mode !== 'OBSERVED' ? '기준 부하가 추정값이라' : effort.basis !== bench.basis ? '감축 기준이 달라' : '기준 연도가 달라') : '관측 원단위가 없어'} 순위를 매기지 않습니다. 중앙값 {formatMetric(bench.median, 'kWh/m²·년', 2)}.</>}</p>
    <p className="muted">{bench.note} 비교 대상: 같은 연도에 관측 원단위가 있는 행정동 {bench.count}곳 / 전체 {bench.admin_total}곳.</p>
  </section>;
}

export function ScenarioComparePanel({ scenarios, onRemove, onClear }: { scenarios: SavedScenario[]; onRemove: (id: string) => void; onClear: () => void }) {
  const rows = comparisonRows(scenarios);
  const download = () => {
    const blob = new Blob([scenariosCsv(scenarios)], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a'); a.href = url; a.download = `area-scenarios-${new Date().toISOString().slice(0, 10)}.csv`; a.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  return <section className="panel area-compare" aria-label="시나리오 비교" data-testid="area-compare">
    <div className="panel-title"><h3>시나리오 비교 ({scenarios.length}/{MAX_SCENARIOS})</h3>
      <div className="badge-row"><button type="button" className="button small" onClick={download} disabled={!scenarios.length}><Download size={14} />CSV(엑셀) 내보내기</button><button type="button" className="button ghost small" onClick={onClear} disabled={!scenarios.length}>모두 지우기</button></div></div>
    {!scenarios.length ? <p className="muted">위 막대의 <b>시나리오 저장</b>을 누르면 지금 구역·계획·목표·수단과 엔진 결과를 저장해 최대 {MAX_SCENARIOS}개까지 나란히 봅니다. 이 브라우저에만 저장되며, 링크로 다시 열면 같은 조건으로 다시 계산합니다.</p>
      : <div className="table-wrap"><table className="area-compare-table">
        <thead><tr><th scope="col">항목</th>{scenarios.map((s) => <th key={s.id} scope="col"><span>{s.name}</span><span className="area-compare-actions">{s.link ? <a className="icon-link" href={s.link} title="이 조건으로 다시 열기"><ExternalLink size={13} /><span className="sr-only">다시 열기</span></a> : null}<button type="button" className="icon-link" onClick={() => onRemove(s.id)} title="삭제"><Trash2 size={13} /><span className="sr-only">{s.name} 삭제</span></button></span></th>)}</tr></thead>
        <tbody>{rows.map((r) => <tr key={r.label}><th scope="row">{r.label}</th>{r.values.map((v, i) => <td key={scenarios[i].id} className={/^[\d,.\-]/.test(v) ? 'num' : undefined}>{v}</td>)}</tr>)}</tbody>
      </table></div>}
  </section>;
}
