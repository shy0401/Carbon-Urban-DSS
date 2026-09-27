import { Info, Play, RotateCcw, Scale } from 'lucide-react';
import { FormEvent, useMemo, useState, useEffect, useRef } from 'react';
import type { EChartsOption } from 'echarts';
import { baseChart, compactAxis, lineSeries, missingBands } from '../lib/chartTheme';
import { TOKENS } from '../theme/palette';
import { Link } from 'react-router-dom';
import { useAnalysisScope } from '../hooks/useAnalysisScope';
import { Chart } from '../components/Chart';
import { PageHeader } from '../components/PageHeader';
import { ProvenanceBadge } from '../components/ProvenanceBadge';
import { Massing3D, type SitePlacement } from '../components/Massing3D';
import { QualityBadge } from '../components/QualityBadge';
import { EmptyState, ErrorState } from '../components/Status';
import { api } from '../lib/api';
import { formatMetric } from '../lib/format';
import { provenanceFromCode } from '../lib/provenance';
import { validateScenario, type ScenarioErrors } from '../lib/scenario';
import { applyFloorPreset } from '../lib/capacity';
import { useSystemInfo } from '../hooks/useSystemInfo';
import type { ScenarioInput, ScenarioResult, ScenarioSeries, ZoningCheck } from '../types';
import { zoneBasisLabel, zoneName, zoningSourceNote, zoningTitle, zoningTone } from '../lib/zoning';

const initial: ScenarioInput = { site_area: 10000, building_count: 4, footprint_per_building: 700, floors: 12, households: 240, population: 560, efficiency_factor: 0.85, pv_ratio: 0.2, green_ratio: 0.25, average_household_area: 84 };
const fields: Array<{ key: keyof ScenarioInput; label: string; unit: string; step?: number; min?: number; max?: number }> = [
  { key: 'site_area', label: '대지면적', unit: 'm²', min: 1 }, { key: 'building_count', label: '건물 수', unit: '동', min: 1 },
  { key: 'footprint_per_building', label: '동별 건축면적', unit: 'm²', min: 0 }, { key: 'floors', label: '층수', unit: '층', min: 3, max: 40 },
  { key: 'households', label: '세대수', unit: '세대', min: 0 }, { key: 'population', label: '계획 인구', unit: '명', min: 0 },
  { key: 'efficiency_factor', label: '효율 계수', unit: '배', step: 0.05, min: 0.05, max: 2 }, { key: 'pv_ratio', label: '태양광 전력 대체율', unit: '비율', step: 0.05, min: 0, max: 1 },
  { key: 'green_ratio', label: '녹지 비율', unit: '비율', step: 0.05, min: 0, max: 1 }, { key: 'average_household_area', label: '평균 세대면적', unit: 'm²', min: 1 },
];
const fieldGroups: Array<{ title: string; keys: Array<keyof ScenarioInput> }> = [
  { title: '대지·건축 규모', keys: ['site_area', 'building_count', 'footprint_per_building', 'floors'] },
  { title: '수용 인구', keys: ['households', 'population', 'average_household_area'] },
  { title: '에너지·녹지 가정', keys: ['efficiency_factor', 'pv_ratio', 'green_ratio'] },
];

interface OptimizationResult { status?: string; objective?: string; legal_status?: string; method?: string; explanation?: string; reason?: string; limitations?: string[]; alternatives?: Array<Record<string, unknown>>; candidates?: Array<Record<string, unknown>>; }

export function SimulationPage() {
  const {year,gridId,region}=useAnalysisScope();
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
  const [site, setSite] = useState<SitePlacement | null>(null);
  const [liveZoning, setLiveZoning] = useState<ZoningCheck | null>(null);
  const system = useSystemInfo();
  useEffect(()=>{revision.current++;setResult(null);setOptimization(null);setRequestError(null);},[input,year,gridId,site,region]);
  useEffect(()=>{setSite(null);},[gridId]);
  const sitePayload = site ? { site_lon: site.lon, site_lat: site.lat, site_rotation: Math.min(89.9, Math.max(0, site.rotation)) } : {};
  const massingGrid = gridId || result?.grid_id || system?.default_grid_id || null;
  useEffect(()=>{revision.current++;setOptimization(null);},[constraints]);
  const series = useMemo(() => result ? extractMonthly(result, active) : [], [result, active]);
  // 현황 --ink 실선, 시나리오 --plan-a 짧은 점선(1 3), 증감은 부호별 증감 램프 막대. 값이 없는 달은 비워 둔다.
  const chartOption = useMemo<EChartsOption>(() => {
    const labels = series.map((row) => monthLabel(row.month ?? row.use_ym));
    const values = series.map((row) => numericValue(row));
    const base = baseChart();
    const unit = series.some((row) => typeof row.carbon_kg === 'number') ? 'kgCO₂eq' : 'kWh';
    const kind = active === 'scenario' ? '시나리오' : active === 'difference' ? '시나리오 − 현황' : '관측 원단위 기반 현황';
    const line = active === 'difference'
      ? { name: activeLabel(active), type: 'bar' as const, barMaxWidth: 18, data: values.map((v) => (v === null ? null : { value: v, itemStyle: { color: v < 0 ? TOKENS['diff-neg-2'] : v > 0 ? TOKENS['diff-pos-2'] : TOKENS['diff-zero'] } })) }
      : lineSeries(activeLabel(active), values, active === 'scenario' ? TOKENS['plan-a'] : TOKENS.ink, active === 'scenario' ? 'scenario' : 'solid');
    return baseChart({
      legend: { show: false },
      grid: { left: 64, right: 20, top: 30, bottom: 30 },
      tooltip: { ...(base.tooltip as object), valueFormatter: (value: unknown) => (typeof value === 'number' ? `${formatMetric(value, unit, 1)} (${kind})` : '자료 없음') },
      xAxis: { ...(base.xAxis as object), data: labels },
      yAxis: { ...(base.yAxis as object), name: unit, axisLabel: { ...((base.yAxis as { axisLabel?: object }).axisLabel ?? {}), formatter: compactAxis } },
      series: [{ ...line, markArea: missingBands(labels, [values]) }],
    });
  }, [series, active]);

  const submit = async (event?: FormEvent) => {
    event?.preventDefault();
    const nextErrors = validateScenario(input);
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;
    setSubmitting(true); setRequestError(null);const current=revision.current;
    try { const next=await api<ScenarioResult>('/scenarios', { method: 'POST', body: JSON.stringify({...input,...sitePayload,year,grid_id:gridId,region}) });if(current===revision.current)setResult(next); }
    catch (reason) { setRequestError(reason instanceof Error ? reason.message : '시나리오 계산에 실패했습니다.'); }
    finally { setSubmitting(false); }
  };
  const optimize = async () => {
    const nextErrors = validateScenario(input); setErrors(nextErrors); if (Object.keys(nextErrors).length) return;
    setOptimizing(true); setRequestError(null);const current=revision.current;
    try { const next=await api<OptimizationResult>('/optimize', { method: 'POST', body: JSON.stringify({ ...input,...sitePayload,year,grid_id:gridId,region, min_households: constraints.min_households, min_population: constraints.min_population }) });if(current===revision.current)setOptimization(next); }
    catch (reason) { setRequestError(reason instanceof Error ? reason.message : '최적화에 실패했습니다.'); }
    finally { setOptimizing(false); }
  };
  const preset = (floors: number) => setInput((old) => ({ ...old, ...applyFloorPreset(old, floors) }));
  const [sceneSaved, setSceneSaved] = useState<string | null>(null);
  useEffect(() => { setSceneSaved(null); }, [result?.id]);
  // The 3D scene is stored with the saved scenario so the report can show it (PNG from the browser canvas).
  const saveScene = async (dataUrl: string) => {
    if (!result?.id) return;
    try { await api(`/scenarios/${result.id}/image`, { method: 'PUT', body: JSON.stringify({ data_url: dataUrl }) }); setSceneSaved(result.id); }
    catch (reason) { setRequestError(reason instanceof Error ? reason.message : '3D 장면 저장에 실패했습니다.'); }
  };

  const zoning = result?.zoning_check ?? liveZoning;
  return <div className="page simulation-page">
    <PageHeader title="탄소 시뮬레이션" description="개발 조건을 바꾸면 3D 배치·용도지역 상한·에너지·탄소 1차 추정이 함께 바뀝니다." action={<span className="badge warn"><Info size={13} />의사결정 전 검토 필요</span>} />
    <div className="simulation-context"><span>기준 {year}년 · 격자 {massingGrid ?? '예비 선정 격자'}{site ? ' · 대지 위치 지정됨' : ' · 대지는 격자 중심'}</span><span>입력값은 예시이며 실제 현재 배치가 아닙니다</span></div>
    <div className="simulation-layout">
      <form className="panel scenario-form" onSubmit={submit}>
        <div className="panel-title"><h3>개발 조건</h3></div>
        <div className="floor-presets"><span>층수·수용량 빠른 설정</span><div>{[5, 10, 20, 30, 40].map((floors) => <button type="button" className={input.floors === floors ? 'active' : ''} key={floors} onClick={() => preset(floors)}>{floors}층</button>)}</div><small>연면적과 평균 세대면적으로 세대수를 다시 계산하고 현재 가구당 인구비를 적용합니다.</small></div>
        {fieldGroups.map((group) => <fieldset className="field-group" key={group.title}><legend>{group.title}</legend><div className="field-grid">{group.keys.map((key) => { const field = fields.find((f) => f.key === key)!; return <label className={errors[field.key] ? 'field error' : 'field'} key={field.key}><span>{field.label}</span><div><input type="number" value={input[field.key]} step={field.step ?? 1} min={field.min} max={field.max} onChange={(event) => setInput((old) => ({ ...old, [field.key]: Number(event.target.value) }))} /><em>{field.unit}</em></div>{errors[field.key] && <small>{errors[field.key]}</small>}</label>; })}</div></fieldset>)}
        <div className="derived-strip"><div><span>예상 연면적</span><strong>{formatMetric(input.building_count * input.footprint_per_building * input.floors, 'm²')}</strong></div><div><span>계획 용적률</span><strong>{formatMetric((input.building_count * input.footprint_per_building * input.floors / input.site_area) * 100, '%', 1)}</strong></div><div><span>계획 건폐율</span><strong>{formatMetric((input.building_count * input.footprint_per_building / input.site_area) * 100, '%', 1)}</strong></div></div>
        <div className="form-actions"><button type="button" className="button ghost" onClick={() => { setInput(initial); setErrors({}); setResult(null); setSite(null); }}><RotateCcw size={15} />초기화</button><button className="button primary" disabled={submitting}><Play size={15} />{submitting ? '계산 중…' : '시나리오 계산'}</button></div>
      </form>
      <div className="simulation-main">
        <section className="panel massing-panel"><div className="panel-title"><h3>3D 배치·일조</h3><span className="status-tag neutral">규모 비교용 개념 배치</span></div><Massing3D gridId={massingGrid} region={region} input={input} site={site} onSiteChange={setSite} onZoning={setLiveZoning} onCapture={result?.id ? saveScene : undefined} captureLabel="보고서용 장면 저장" /></section>
        <section className="panel scenario-result">
          <div className="panel-title"><h3>에너지·탄소 비교</h3>{result && <div className="badge-row">{provenanceFromCode(result.data_class) && <ProvenanceBadge kind={provenanceFromCode(result.data_class)!} />}{result.quality && <QualityBadge value={result.quality} />}</div>}</div>
          {requestError && <ErrorState message={requestError} onRetry={() => void submit()} />}
          {!requestError && !result && <div className="scenario-empty"><h3>조건을 정하고 ‘시나리오 계산’을 누르세요</h3><p>서버가 보유한 관측 원단위로 계산하며, 근거 자료가 없으면 임의의 결과를 만들지 않습니다. 3D 배치와 용도지역 확인은 계산 전에도 바로 바뀝니다.</p></div>}
          {result && <>{result.id && <Link className="button secondary report-from-scenario" to={`/reports?scenario=${result.id}`}>이 계획안으로 보고서 작성{sceneSaved === result.id ? ' (3D 장면 포함)' : ''}</Link>}{result.total_footprint !== undefined && <div className="calculation-strip"><div><span>건축면적 합계</span><strong>{formatMetric(result.total_footprint, 'm²')}</strong></div><div><span>연면적</span><strong>{formatMetric(result.gross_floor_area, 'm²')}</strong></div><div><span>용적률</span><strong>{formatMetric(result.far, '%', 1)}</strong></div><div><span>건폐율</span><strong>{formatMetric(result.bcr, '%', 1)}</strong></div></div>}<div className="tabs" role="tablist">{(['current', 'scenario', 'difference'] as const).map((tab) => <button key={tab} role="tab" aria-selected={active === tab} onClick={() => setActive(tab)}>{activeLabel(tab, !!result.baseline_estimate)}</button>)}</div>
            {result.baseline_estimate && <p className="estimate-note" role="note"><Info size={15} aria-hidden="true" />이 격자에는 12개월 관측과 연면적이 모두 있는 지번이 없어 <b>{result.baseline_estimate.label}</b>(관측 지번 {result.baseline_estimate.parcels}곳, 연면적 {formatMetric(result.baseline_estimate.area_m2, 'm²')})로 추정했습니다.</p>}
            <div className="result-metrics">{metricEntries(annualFor(result, active)).map(([key, value]) => <div key={key}><span>{metricLabel(key)}</span><strong>{formatMetric(value, metricUnit(key), 1)}</strong></div>)}</div>
            {allMissing(annualFor(result, active)) ? <div className="missing-reason"><Info size={18} /><div><strong>기준 자료가 없어 추정할 수 없습니다</strong><p>{result.quality ?? '공간 매칭된 기준 에너지 또는 기준 연면적이 없습니다.'}</p></div></div> : series.length > 0 && <Chart option={chartOption} height={270} ariaLabel={`${activeLabel(active, !!result.baseline_estimate)} 월별 시나리오 차트`} />}
            <div className="assumption-note"><strong>해석 범위</strong><p>{result.limitation ?? `${result.label ?? '원단위 기반 1차 추정'} 결과이며, 설계·인허가 수치로 사용할 수 없습니다.`}</p>{result.assumptions?.length ? <ul>{result.assumptions.map((assumption) => <li key={assumption}>{assumption}</li>)}</ul> : null}</div></>}
          {zoning && <ZoningSummary zoning={zoning} saved={!!result?.zoning_check} />}
        </section>
      </div>
    </div>
    <section className="panel optimization-panel"><div className="panel-title"><h3>도시구조 최적화</h3><span className="status-tag neutral">결정론적 계산</span></div><p className="panel-description">최소 수용 목표를 충족하는 후보를 같은 입력과 제약에서 항상 같은 순서로 탐색합니다. 대지의 용도지역이 확인되면 법적 상한(전주시는 도시계획 조례 기본 상한, 조례를 등록하지 않은 지역은 국토계획법 시행령 상한) 안의 후보만 봅니다.</p><div className="optimization-controls"><label><span>최소 세대수</span><input type="number" min="0" value={constraints.min_households} onChange={(event) => setConstraints((old) => ({ ...old, min_households: Number(event.target.value) }))} /></label><label><span>최소 인구</span><input type="number" min="0" value={constraints.min_population} onChange={(event) => setConstraints((old) => ({ ...old, min_population: Number(event.target.value) }))} /></label><button type="button" className="button secondary" onClick={() => void optimize()} disabled={optimizing}>{optimizing ? '탐색 중…' : '최적안 탐색'}</button></div>{optimization && <OptimizationResults result={optimization} onApply={(row) => setInput((old) => ({ ...old, building_count: Number(row.building_count), floors: Number(row.floors), households: Number(row.households), population: Number(row.population) }))} />}</section>
  </div>;
}

function ZoningSummary({ zoning, saved }: { zoning: ZoningCheck; saved: boolean }) {
  const check = zoning.check;
  const tone = zoningTone(check?.label);
  const special = zoning.special;
  return <div className="zoning-summary">
    <div className="zoning-summary-head"><Scale size={16} aria-hidden="true" /><strong>{zoningTitle(zoning)} 1차 확인</strong><span className={`status-tag ${tone}`}>{check?.label ?? '판단 보류'}</span><small>{saved ? '계산 시점 기준' : '현재 입력 기준'}</small></div>
    {(special?.greenbelt || special?.district_plans?.length) ? <p className="zoning-special">
      {special.greenbelt && <span className="status-tag bad">개발제한구역 {special.greenbelt.share.toFixed(0)}%</span>}
      {special.district_plans.map((area) => <span key={`${area.name}-${area.area_m2}`} className="status-tag warn">지구단위계획구역 {area.name ?? ''} {area.share.toFixed(0)}%</span>)}
    </p> : null}
    <table><thead><tr><th>용도지역</th><th>근거</th><th className="num">대지 비율</th><th className="num">건폐율 상한</th><th className="num">용적률 상한</th></tr></thead>
      <tbody>{zoning.zones.length ? zoning.zones.map((z) => <tr key={`${z.zone}-${z.zone_name}-${z.gap ? 'gap' : ''}`}><td>{zoneName(z)}{z.note && <small>{z.note}</small>}</td><td>{zoneBasisLabel(z)}</td><td className="num">{z.share != null ? `${z.share.toFixed(1)}%` : '-'}</td><td className="num">{(z.applied_bcr_limit ?? z.bcr_limit) != null ? `${z.applied_bcr_limit ?? z.bcr_limit}%` : '규정 없음'}</td><td className="num">{(z.applied_far_limit ?? z.far_limit) != null ? `${z.applied_far_limit ?? z.far_limit}%` : '확인 필요'}</td></tr>) : <tr><td colSpan={5}>{zoning.reason ?? '대지와 겹치는 용도지역 자료가 없습니다.'}</td></tr>}</tbody>
    </table>
    {check?.notes?.length ? <ul>{check.notes.map((n) => <li key={n}>{n}</li>)}</ul> : null}
    {zoning.source && <p className="muted">근거: <a href={zoning.source.url} target="_blank" rel="noreferrer">{zoning.source.name}</a>{zoning.source.articles ? ` ${zoning.source.articles}` : ''} ({[zoning.source.number, zoning.source.effective ? `${zoning.source.effective} 시행` : null, zoning.source.checked ? `${zoning.source.checked} 확인` : null].filter(Boolean).join(', ')}). {zoningSourceNote(zoning)}</p>}
  </div>;
}

/** '현재' is this grid's observed use; with a pooled estimate it is the planned area at the region's average intensity. */
function activeLabel(key: 'current' | 'scenario' | 'difference', estimated = false) { return ({ current: estimated ? '지역 평균 기준 (BAU)' : '현재', scenario: '시나리오', difference: estimated ? '기준 대비 증감' : '증감' })[key]; }
function annualFor(result: ScenarioResult, key: 'current' | 'scenario' | 'difference'): ScenarioSeries | null { return (result.annual?.[key] as ScenarioSeries | null) ?? (!Array.isArray(result[key]) ? result[key] as ScenarioSeries : null) ?? null; }
function metricEntries(series: ScenarioSeries | null): Array<[string, number | null]> { if (!series) return [['energy_kwh', null], ['carbon_kg', null]]; return Object.entries(series).filter(([, value]) => typeof value === 'number' || value === null).slice(0, 4) as Array<[string, number | null]>; }
function metricLabel(key: string) { return ({ electricity_kwh: '전력', gas_kwh: '가스', energy_kwh: '에너지', carbon_kg: '전체 탄소 (전력+가스)', electricity_carbon_kg: '전력 탄소' } as Record<string, string>)[key] ?? key.replaceAll('_', ' '); }
function metricUnit(key: string) { return key.includes('carbon') ? 'kgCO₂eq' : key.includes('far') || key.includes('ratio') ? '%' : 'kWh'; }
function extractMonthly(result: ScenarioResult, active: string): Array<Record<string, unknown>> { if (Array.isArray(result.monthly)) return result.monthly.map((row) => { const nested = row[active]; return nested && typeof nested === 'object' ? { month: row.month ?? row.use_ym, ...(nested as Record<string, unknown>) } : { month: row.month ?? row.use_ym, value: row[active] }; }); const direct = result[active as keyof ScenarioResult]; return Array.isArray(direct) ? direct.filter((row): row is Record<string, unknown> => !!row && typeof row === 'object') : []; }
function numericValue(row: Record<string, unknown>) { for (const key of ['carbon_kg', 'energy_kwh', 'electricity_kwh', 'value']) if (typeof row[key] === 'number') return row[key]; return null; }
function allMissing(series: ScenarioSeries | null) { return !series || Object.values(series).every((value) => value === null || value === undefined); }

function OptimizationResults({ result, onApply }: { result: OptimizationResult; onApply: (row: Record<string, unknown>) => void }) { const rows = result.alternatives ?? result.candidates ?? []; return <div className="optimization-results"><div className="optimization-status">{result.status && <QualityBadge value={result.status} />}<strong>{result.legal_status ?? 'ENERGY_OPTIMAL · 법적 상한 미확정'}</strong><p>{result.explanation ?? result.reason ?? '서버가 반환한 제약 충족 후보를 목적함수 순으로 표시합니다.'}</p></div>{rows.length ? <div className="alternative-grid">{rows.slice(0, 5).map((row, index) => <article key={String(row.id ?? index)}><span>{String(row.label ?? row.objective ?? `대안 ${index + 1}`)}</span><h4>{row.floors === null || row.floors === undefined ? '층수 자료 없음' : `${row.floors}층 · ${row.building_count ?? '—'}동`}</h4><dl>{OPTIMIZATION_FIELDS.map(([key, label, unit, digits]) => <div key={key}><dt>{label}</dt><dd>{typeof row[key] === 'number' ? formatMetric(row[key] as number, unit, digits) : '자료 없음'}</dd></div>)}</dl>{typeof row.floors === 'number' && typeof row.building_count === 'number' && <button type="button" className="button ghost small" onClick={() => onApply(row)}>이 조건을 입력에 적용</button>}</article>)}</div> : <EmptyState title="제약을 충족하는 후보가 없습니다" />}{result.limitations?.length ? <ul className="optimization-limitations">{result.limitations.map((item) => <li key={item}>{item}</li>)}</ul> : null}</div>; }
const OPTIMIZATION_FIELDS: Array<[string, string, string, number]> = [['far', '용적률', '%', 1], ['bcr', '건폐율', '%', 1], ['households', '세대수', '세대', 0], ['population', '인구', '명', 0], ['annual_electricity_kwh', '연간 전력', 'kWh', 0], ['annual_carbon_kg', '연간 전체 탄소', 'kgCO₂eq', 0]];
function monthLabel(value: unknown) { const text = String(value ?? ''); const month = Number(text.replace('-', '').slice(-2)); return month >= 1 && month <= 12 ? `${month}월` : text; }
