import { Calculator, Info, Leaf, Play, RotateCcw } from 'lucide-react';
import { FormEvent, useMemo, useState, useEffect, useRef } from 'react';
import type { EChartsOption } from 'echarts';
import { Link } from 'react-router-dom';
import { useAnalysisScope } from '../hooks/useAnalysisScope';
import { Chart } from '../components/Chart';
import { PageHeader } from '../components/PageHeader';
import { QualityBadge } from '../components/QualityBadge';
import { EmptyState, ErrorState } from '../components/Status';
import { api } from '../lib/api';
import { formatMetric } from '../lib/format';
import { validateScenario, type ScenarioErrors } from '../lib/scenario';
import { applyFloorPreset } from '../lib/capacity';
import type { ScenarioInput, ScenarioResult, ScenarioSeries } from '../types';

const initial: ScenarioInput = { site_area: 10000, building_count: 4, footprint_per_building: 700, floors: 12, households: 240, population: 560, efficiency_factor: 0.85, pv_ratio: 0.2, green_ratio: 0.25, average_household_area: 84 };
const fields: Array<{ key: keyof ScenarioInput; label: string; unit: string; step?: number; min?: number; max?: number }> = [
  { key: 'site_area', label: '대지면적', unit: 'm²', min: 1 }, { key: 'building_count', label: '건물 수', unit: '동', min: 1 },
  { key: 'footprint_per_building', label: '동별 건축면적', unit: 'm²', min: 0 }, { key: 'floors', label: '층수', unit: '층', min: 3, max: 40 },
  { key: 'households', label: '세대수', unit: '세대', min: 0 }, { key: 'population', label: '계획 인구', unit: '명', min: 0 },
  { key: 'efficiency_factor', label: '효율 계수', unit: '배', step: 0.05, min: 0.05, max: 2 }, { key: 'pv_ratio', label: '전력 수요 대체율', unit: '비율', step: 0.05, min: 0, max: 1 },
  { key: 'green_ratio', label: '녹지 비율', unit: '비율', step: 0.05, min: 0, max: 1 }, { key: 'average_household_area', label: '평균 세대면적', unit: 'm²', min: 1 },
];

interface OptimizationResult { status?: string; objective?: string; legal_status?: string; method?: string; explanation?: string; reason?: string; limitations?: string[]; alternatives?: Array<Record<string, unknown>>; candidates?: Array<Record<string, unknown>>; }

export function SimulationPage() {
  const {year,gridId}=useAnalysisScope();
  const revision=useRef(0);
  const [input, setInput] = useState(initial);
  const [errors, setErrors] = useState<ScenarioErrors>({});
  const [result, setResult] = useState<ScenarioResult | null>(null);
  const [active, setActive] = useState<'current' | 'scenario' | 'difference'>('scenario');
  const [submitting, setSubmitting] = useState(false);
  const [requestError, setRequestError] = useState<string | null>(null);
  const [constraints, setConstraints] = useState({ min_households: 500, min_population: 1200 });
  const [optimization, setOptimization] = useState<OptimizationResult | null>(null);
  const [optimizing, setOptimizing] = useState(false);
  useEffect(()=>{revision.current++;setResult(null);setOptimization(null);setRequestError(null);},[input,year,gridId]);
  useEffect(()=>{revision.current++;setOptimization(null);},[constraints]);
  const series = useMemo(() => result ? extractMonthly(result, active) : [], [result, active]);
  const chartOption = useMemo<EChartsOption>(() => ({
    color: [active === 'difference' ? '#f97316' : active === 'scenario' ? '#0f766e' : '#475569'],
    tooltip: { trigger: 'axis' }, grid: { left: 60, right: 20, top: 30, bottom: 35 },
    xAxis: { type: 'category', data: series.map((row) => String(row.month ?? row.use_ym ?? '')), axisLabel: { color: '#64748b' } },
    yAxis: { type: 'value', splitLine: { lineStyle: { color: '#edf2f4' } }, axisLabel: { color: '#64748b' } },
    series: [{ name: activeLabel(active), type: 'line', smooth: true, symbolSize: 7, data: series.map((row) => numericValue(row)), areaStyle: { opacity: 0.1 } }],
  }), [series, active]);

  const submit = async (event?: FormEvent) => {
    event?.preventDefault();
    const nextErrors = validateScenario(input);
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;
    setSubmitting(true); setRequestError(null);const current=revision.current;
    try { const next=await api<ScenarioResult>('/scenarios', { method: 'POST', body: JSON.stringify({...input,year,grid_id:gridId}) });if(current===revision.current)setResult(next); }
    catch (reason) { setRequestError(reason instanceof Error ? reason.message : '시나리오 계산에 실패했습니다.'); }
    finally { setSubmitting(false); }
  };
  const optimize = async () => {
    const nextErrors = validateScenario(input); setErrors(nextErrors); if (Object.keys(nextErrors).length) return;
    setOptimizing(true); setRequestError(null);const current=revision.current;
    try { const next=await api<OptimizationResult>('/optimize', { method: 'POST', body: JSON.stringify({ ...input,year,grid_id:gridId, min_households: constraints.min_households, min_population: constraints.min_population }) });if(current===revision.current)setOptimization(next); }
    catch (reason) { setRequestError(reason instanceof Error ? reason.message : '최적화에 실패했습니다.'); }
    finally { setOptimizing(false); }
  };
  const preset = (floors: number) => setInput((old) => ({ ...old, ...applyFloorPreset(old, floors) }));

  return <div className="page simulation-page">
    <PageHeader eyebrow="PRELIMINARY SCENARIO" title="탄소 시뮬레이션" description="관측 원단위를 적용해 개발 조건 변화의 1차 추정치를 비교합니다." action={<span className="badge warn"><Info size={13} />의사결정 전 검토 필요</span>} />
    <div className="simulation-context"><span>기준 {year}년 · {gridId || '예비 선정 격자'}</span><span>입력 예시이며 실제 현재 배치가 아닙니다</span></div><div className="simulation-layout">
      <form className="panel scenario-form" onSubmit={submit}>
        <div className="panel-title"><div><span>INPUT CONDITIONS</span><h3>개발 조건</h3></div><Calculator size={20} /></div>
        <div className="floor-presets"><span>층수·수용량 빠른 설정</span><div>{[5, 10, 20, 30, 40].map((floors) => <button type="button" className={input.floors === floors ? 'active' : ''} key={floors} onClick={() => preset(floors)}>{floors}층</button>)}</div><small>연면적과 평균 세대면적으로 세대수를 다시 계산하고 현재 가구당 인구비를 적용합니다.</small></div>
        <div className="field-grid">{fields.map((field) => <label className={errors[field.key] ? 'field error' : 'field'} key={field.key}><span>{field.label}</span><div><input type="number" value={input[field.key]} step={field.step ?? 1} min={field.min} max={field.max} onChange={(event) => setInput((old) => ({ ...old, [field.key]: Number(event.target.value) }))} /><em>{field.unit}</em></div>{errors[field.key] && <small>{errors[field.key]}</small>}</label>)}</div>
        <div className="derived-strip"><div><span>예상 연면적</span><strong>{formatMetric(input.building_count * input.footprint_per_building * input.floors, 'm²')}</strong></div><div><span>계획 용적률</span><strong>{formatMetric((input.building_count * input.footprint_per_building * input.floors / input.site_area) * 100, '%', 1)}</strong></div></div>
        <div className="form-actions"><button type="button" className="button ghost" onClick={() => { setInput(initial); setErrors({}); setResult(null); }}><RotateCcw size={15} />초기화</button><button className="button primary" disabled={submitting}><Play size={15} />{submitting ? '계산 중…' : '시나리오 계산'}</button></div>
      </form>
      <section className="panel scenario-result">
        <div className="panel-title"><div><span>ESTIMATION RESULT</span><h3>에너지·탄소 비교</h3></div>{result && <QualityBadge value={result.quality ?? 'ESTIMATED'} />}</div>
        {requestError && <ErrorState message={requestError} onRetry={() => void submit()} />}
        {!requestError && !result && <div className="scenario-empty"><ScenarioMassing input={input} /><h3>조건을 입력하고 계산을 시작하세요</h3><p>서버가 보유한 관측 원단위를 이용하며, 근거 자료가 없으면 임의의 결과를 만들지 않습니다.</p></div>}
        {result && <><ScenarioMassing input={input}/>{result.id && <Link className="button secondary report-from-scenario" to={`/reports?scenario=${result.id}`}>이 계획안으로 보고서 작성</Link>}{result.total_footprint !== undefined && <div className="calculation-strip"><div><span>건축면적 합계</span><strong>{formatMetric(result.total_footprint, 'm²')}</strong></div><div><span>연면적</span><strong>{formatMetric(result.gross_floor_area, 'm²')}</strong></div><div><span>용적률</span><strong>{formatMetric(result.far, '%', 1)}</strong></div><div><span>건폐율</span><strong>{formatMetric(result.bcr, '%', 1)}</strong></div></div>}<div className="tabs" role="tablist">{(['current', 'scenario', 'difference'] as const).map((tab) => <button key={tab} role="tab" aria-selected={active === tab} onClick={() => setActive(tab)}>{activeLabel(tab)}</button>)}</div>
          <div className="result-metrics">{metricEntries(annualFor(result, active)).map(([key, value]) => <div key={key}><span>{metricLabel(key)}</span><strong>{formatMetric(value, metricUnit(key), 1)}</strong></div>)}</div>
          {allMissing(annualFor(result, active)) ? <div className="missing-reason"><Info size={18} /><div><strong>기준 자료가 없어 추정할 수 없습니다</strong><p>{result.quality ?? '공간 매칭된 기준 에너지 또는 기준 연면적이 없습니다.'}</p></div></div> : series.length > 0 && <Chart option={chartOption} height={270} ariaLabel={`${activeLabel(active)} 월별 시나리오 차트`} />}
          <div className="assumption-note"><strong>해석 범위</strong><p>{result.limitation ?? `${result.label ?? '원단위 기반 1차 추정'} 결과이며, 설계·인허가 수치로 사용할 수 없습니다.`}</p>{result.assumptions?.length ? <ul>{result.assumptions.map((assumption) => <li key={assumption}>{assumption}</li>)}</ul> : null}</div></>}
      </section>
    </div>
    <section className="panel optimization-panel"><div className="panel-title"><div><span>DETERMINISTIC GRID SEARCH</span><h3>도시구조 최적화</h3></div><QualityBadge value="CALCULATED" label="결정론적 계산" /></div><p className="panel-description">최소 수용 목표를 충족하는 후보를 같은 입력과 제약에서 항상 같은 순서로 탐색합니다. 법적 상한 자료가 없으면 에너지 최적안으로만 표시합니다.</p><div className="optimization-controls"><label><span>최소 세대수</span><input type="number" min="0" value={constraints.min_households} onChange={(event) => setConstraints((old) => ({ ...old, min_households: Number(event.target.value) }))} /></label><label><span>최소 인구</span><input type="number" min="0" value={constraints.min_population} onChange={(event) => setConstraints((old) => ({ ...old, min_population: Number(event.target.value) }))} /></label><button className="button primary" onClick={() => void optimize()} disabled={optimizing}>{optimizing ? '탐색 중…' : '최적안 탐색'}</button></div>{optimization && <OptimizationResults result={optimization} />}</section>
  </div>;
}

function activeLabel(key: 'current' | 'scenario' | 'difference') { return ({ current: '현재', scenario: '시나리오', difference: '증감' })[key]; }
function annualFor(result: ScenarioResult, key: 'current' | 'scenario' | 'difference'): ScenarioSeries | null { return (result.annual?.[key] as ScenarioSeries | null) ?? (!Array.isArray(result[key]) ? result[key] as ScenarioSeries : null) ?? null; }
function metricEntries(series: ScenarioSeries | null): Array<[string, number | null]> { if (!series) return [['energy_kwh', null], ['carbon_kg', null]]; return Object.entries(series).filter(([, value]) => typeof value === 'number' || value === null).slice(0, 4) as Array<[string, number | null]>; }
function metricLabel(key: string) { return ({ electricity_kwh: '전력', gas_kwh: '가스', energy_kwh: '에너지', carbon_kg: '탄소 배출' } as Record<string, string>)[key] ?? key.replaceAll('_', ' '); }
function metricUnit(key: string) { return key.includes('carbon') ? 'kgCO₂eq' : key.includes('far') || key.includes('ratio') ? '%' : 'kWh'; }
function extractMonthly(result: ScenarioResult, active: string): Array<Record<string, unknown>> { if (Array.isArray(result.monthly)) return result.monthly.map((row) => { const nested = row[active]; return nested && typeof nested === 'object' ? { month: row.month ?? row.use_ym, ...(nested as Record<string, unknown>) } : { month: row.month ?? row.use_ym, value: row[active] }; }); const direct = result[active as keyof ScenarioResult]; return Array.isArray(direct) ? direct.filter((row): row is Record<string, unknown> => !!row && typeof row === 'object') : []; }
function numericValue(row: Record<string, unknown>) { for (const key of ['carbon_kg', 'energy_kwh', 'electricity_kwh', 'value']) if (typeof row[key] === 'number') return row[key]; return null; }
function allMissing(series: ScenarioSeries | null) { return !series || Object.values(series).every((value) => value === null || value === undefined); }

function ScenarioMassing({ input }: { input: ScenarioInput }) { return <div className="massing" aria-label={`${input.building_count}개 동 ${input.floors}층 계획 모형`}><div className="massing-ground">{Array.from({ length: Math.min(input.building_count, 12) }, (_, index) => <span key={index} style={{ height: `${Math.max(28, Math.min(125, input.floors * 3))}px` }}><i>{input.floors}F</i></span>)}</div><small>개념 배치 · 축척 없음</small></div>; }
function OptimizationResults({ result }: { result: OptimizationResult }) { const rows = result.alternatives ?? result.candidates ?? []; return <div className="optimization-results"><div className="optimization-status"><QualityBadge value={result.status ?? 'CALCULATED'} /><strong>{result.legal_status ?? 'ENERGY_OPTIMAL · 법적 상한 미확정'}</strong><p>{result.explanation ?? result.reason ?? '서버가 반환한 제약 충족 후보를 목적함수 순으로 표시합니다.'}</p></div>{rows.length ? <div className="alternative-grid">{rows.slice(0, 5).map((row, index) => <article key={String(row.id ?? index)}><span>{String(row.label ?? row.objective ?? `대안 ${index + 1}`)}</span><h4>{row.floors === null || row.floors === undefined ? '층수 자료 없음' : `${row.floors}층 · ${row.building_count ?? '—'}동`}</h4><dl>{['far', 'bcr', 'households', 'population', 'annual_carbon_kg'].map((key) => <div key={key}><dt>{metricLabel(key)}</dt><dd>{typeof row[key] === 'number' ? formatMetric(row[key] as number, metricUnit(key), 1) : '자료 없음'}</dd></div>)}</dl></article>)}</div> : <EmptyState title="제약을 충족하는 후보가 없습니다" />}{result.limitations?.length ? <ul className="optimization-limitations">{result.limitations.map((item) => <li key={item}>{item}</li>)}</ul> : null}</div>; }
