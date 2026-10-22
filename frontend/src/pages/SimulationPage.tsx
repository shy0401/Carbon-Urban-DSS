import { FileText, Info, Link2, Play, RotateCcw } from 'lucide-react';
import { FormEvent, useMemo, useState, useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { setAnalysisScope, useAnalysisScope } from '../hooks/useAnalysisScope';
import { parseScenarioLink, scenarioLink, type ScenarioLink } from '../lib/caseLink';
import { Chart } from '../components/Chart';
import { PageHeader } from '../components/PageHeader';
import { ProvenanceBadge } from '../components/ProvenanceBadge';
import { Massing3D, type SitePlacement } from '../components/Massing3D';
import { QualityBadge } from '../components/QualityBadge';
import { EmptyState, ErrorState } from '../components/Status';
import { ZoningSummary } from '../components/ZoningSummary';
import { api } from '../lib/api';
import { formatMetric } from '../lib/format';
import { provenanceFromCode } from '../lib/provenance';
import { validateScenario, type ScenarioErrors } from '../lib/scenario';
import { applyFloorPreset } from '../lib/capacity';
import { annualSide, gasCarbon, hasAnnual, methodText, planChartOption, savingsText, tonnes } from '../lib/plan';
import { useSystemInfo } from '../hooks/useSystemInfo';
import type { ScenarioInput, ScenarioResult, ZoningCheck } from '../types';
import { zoningTone } from '../lib/zoning';

// 기본 입력은 용적률 280%(4동 × 700m² × 10층 ÷ 1만m²)로 흔한 조례 상한 300% 안에 둔다(UX 검토 F14: 12층 336%는 첫 화면부터 상한 초과 경고).
const initial: ScenarioInput = { site_area: 10000, building_count: 4, footprint_per_building: 700, floors: 10, households: 200, population: 467, efficiency_factor: 0.85, pv_ratio: 0.2, green_ratio: 0.25, average_household_area: 84 };
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
  // 사례 링크(/simulation?region=…&grid=…&site=lon,lat,회전&site_area=…): 같은 입력으로 시작한다.
  const linked = useRef<ScenarioLink | null | undefined>(undefined);
  if (linked.current === undefined) linked.current = parseScenarioLink(typeof window === 'undefined' ? '' : window.location.search);
  const [input, setInput] = useState<ScenarioInput>(() => ({ ...initial, ...(linked.current?.input ?? {}) }));
  const [errors, setErrors] = useState<ScenarioErrors>({});
  const [result, setResult] = useState<ScenarioResult | null>(null);
  // 입력을 바꾸면 지난 결과를 지우지 않고 '이전 입력의 결과'로 표시해 둔다(값을 바꿔 가며 견주어 볼 수 있게). 다시 계산하면 풀린다.
  const [stale, setStale] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const navigate = useNavigate();
  const [requestError, setRequestError] = useState<string | null>(null);
  const [constraints, setConstraints] = useState(() => ({ min_households: linked.current?.constraints?.min_households ?? 500, min_population: linked.current?.constraints?.min_population ?? 1200 }));
  const [optimization, setOptimization] = useState<OptimizationResult | null>(null);
  const [optimizing, setOptimizing] = useState(false);
  const [site, setSite] = useState<SitePlacement | null>(null);
  const [liveZoning, setLiveZoning] = useState<ZoningCheck | null>(null);
  const system = useSystemInfo();
  useEffect(()=>{revision.current++;setStale(true);setOptimization(null);setRequestError(null);},[input,year,gridId,site,region]);
  useEffect(()=>{setSite(null);},[gridId]);
  useEffect(() => {
    const l = linked.current; if (!l) return;
    const next: { region?: string | null; gridId?: string | null; year?: number } = {};
    if (l.region !== undefined && l.region !== region) next.region = l.region;
    if (l.grid && l.grid !== gridId) next.gridId = l.grid;
    if (l.year && l.year !== year) next.year = l.year;
    if (Object.keys(next).length) setAnalysisScope(next, { fromLink: true });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  // The linked site is placed once the linked grid is the selected one (choosing a grid clears the site above).
  const pendingSite = useRef(linked.current?.site ?? null);
  useEffect(() => {
    const placed = pendingSite.current; const l = linked.current;
    if (!placed || (l?.grid && l.grid !== gridId) || (l?.region !== undefined && (l.region ?? null) !== region)) return;
    pendingSite.current = null; setSite(placed);
  }, [gridId, region]);
  const [linkUrl, setLinkUrl] = useState<string | null>(null);
  useEffect(() => { setLinkUrl(null); }, [input, site, gridId, region, year, constraints]);
  const copyLink = () => {
    const url = window.location.origin + scenarioLink(input, site, { region, grid: gridId, year }, constraints);
    setLinkUrl(url);
    void navigator.clipboard?.writeText(url).catch(() => undefined);
  };
  const sitePayload = site ? { site_lon: site.lon, site_lat: site.lat, site_rotation: Math.min(89.9, Math.max(0, site.rotation)) } : {};
  const massingGrid = gridId || result?.grid_id || system?.default_grid_id || null;
  useEffect(()=>{revision.current++;setOptimization(null);},[constraints]);
  const chart = useMemo(() => (result ? planChartOption(result) : null), [result]);

  const submit = async (event?: FormEvent) => {
    event?.preventDefault();
    const nextErrors = validateScenario(input);
    setErrors(nextErrors);
    if (Object.keys(nextErrors).length) return;
    setSubmitting(true); setRequestError(null);const current=revision.current;
    try { const next=await api<ScenarioResult>('/scenarios', { method: 'POST', body: JSON.stringify({...input,...sitePayload,year,grid_id:gridId,region}) });if(current===revision.current){setResult(next);setStale(false);} }
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
  const [captureRequest, setCaptureRequest] = useState(0);
  const [reporting, setReporting] = useState(false);
  const reportPending = useRef<string | null>(null);
  useEffect(() => { setSceneSaved(null); reportPending.current = null; setReporting(false); }, [result?.id]);
  // The 3D scene is stored with the saved scenario so the report can show it (PNG from the browser canvas).
  const saveScene = async (dataUrl: string) => {
    if (!result?.id) return;
    const id = result.id;
    try { await api(`/scenarios/${id}/image`, { method: 'PUT', body: JSON.stringify({ data_url: dataUrl }) }); setSceneSaved(id); }
    catch (reason) { setRequestError(reason instanceof Error ? reason.message : '3D 장면 저장에 실패했습니다.'); }
    finally { if (reportPending.current === id) { reportPending.current = null; navigate(`/reports?scenario=${id}&auto=1`); } }
  };
  // '보고서 작성': save the 3D picture first (when the scene can be drawn), then open the report of this plan.
  const openReport = () => {
    if (!result?.id) return;
    const id = result.id;
    if (sceneSaved === id) { navigate(`/reports?scenario=${id}&auto=1`); return; }
    setReporting(true); reportPending.current = id; setCaptureRequest((n) => n + 1);
    window.setTimeout(() => { if (reportPending.current === id) { reportPending.current = null; navigate(`/reports?scenario=${id}&auto=1`); } }, 4000);  // no WebGL: the report goes without the picture
  };

  const zoning = result?.zoning_check ?? liveZoning;
  return <div className="page simulation-page">
    <PageHeader title="탄소 시뮬레이션" description="개발 조건을 바꾸면 3D 배치·용도지역 상한·에너지·탄소 1차 추정이 함께 바뀝니다." action={<span className="badge warn"><Info size={13} />의사결정 전 검토 필요</span>} />
    <div className="simulation-context"><span>기준 {year}년{result?.place ? ` · ${result.place}` : massingGrid ? ' · 선택한 500m 격자' : ' · 기본 대상지'}{site ? ' · 대지 위치 지정됨' : ' · 대지는 격자 중심'}</span><span>입력값은 예시이며 실제 현재 배치가 아닙니다</span></div>
    <div className="simulation-layout">
      <form className="panel scenario-form" onSubmit={submit}>
        <div className="panel-title"><h3>개발 조건</h3></div>
        <div className="floor-presets"><span>층수·수용량 빠른 설정</span><div>{[5, 10, 20, 30, 40].map((floors) => <button type="button" className={input.floors === floors ? 'active' : ''} key={floors} onClick={() => preset(floors)}>{floors}층</button>)}</div><small>연면적과 평균 세대면적으로 세대수를 다시 계산하고 현재 가구당 인구비를 적용합니다.</small></div>
        {fieldGroups.map((group) => <fieldset className="field-group" key={group.title}><legend>{group.title}</legend><div className="field-grid">{group.keys.map((key) => { const field = fields.find((f) => f.key === key)!; return <label className={errors[field.key] ? 'field error' : 'field'} key={field.key}><span>{field.label}</span><div><input type="number" value={input[field.key]} step={field.step ?? 1} min={field.min} max={field.max} onChange={(event) => setInput((old) => ({ ...old, [field.key]: Number(event.target.value) }))} /><em>{field.unit}</em></div>{errors[field.key] && <small>{errors[field.key]}</small>}</label>; })}</div></fieldset>)}
        <div className="derived-strip"><div><span>예상 연면적</span><strong>{formatMetric(input.building_count * input.footprint_per_building * input.floors, 'm²')}</strong></div><div><span>계획 용적률</span><strong>{formatMetric((input.building_count * input.footprint_per_building * input.floors / input.site_area) * 100, '%', 1)}</strong></div><div><span>계획 건폐율</span><strong>{formatMetric((input.building_count * input.footprint_per_building / input.site_area) * 100, '%', 1)}</strong></div></div>
        <div className="form-actions"><button type="button" className="button ghost" onClick={() => { setInput(initial); setErrors({}); setResult(null); setStale(false); setSite(null); }}><RotateCcw size={15} />초기화</button><button type="button" className="button ghost" onClick={copyLink} title="이 지역·격자·대지 위치·입력값을 주소로 복사합니다"><Link2 size={15} />링크 복사</button><button className="button primary" disabled={submitting}><Play size={15} />{submitting ? '계산 중…' : '시나리오 계산'}</button></div>
        {linkUrl && <label className="case-link"><span>이 조건의 링크 (다른 PC에서 열면 같은 입력으로 시작)</span><input readOnly value={linkUrl} onFocus={(event) => event.currentTarget.select()} /></label>}
      </form>
      <div className="simulation-main">
        <section className="panel massing-panel"><div className="panel-title"><h3>3D 배치·일조</h3><span className="status-tag neutral">규모 비교용 개념 배치</span></div><Massing3D gridId={massingGrid} region={region} input={input} site={site} onSiteChange={setSite} onZoning={setLiveZoning} onCapture={result?.id && !stale ? saveScene : undefined} captureKey={result?.id ?? null} captureRequest={captureRequest} captureLabel="보고서용 장면 저장" /></section>
        <section className="panel scenario-result">
          <div className="panel-title"><h3>계획안 결과</h3>{result && <div className="badge-row">{stale && <span className="status-tag warn" data-testid="scenario-stale">이전 입력의 결과 · 다시 계산 필요</span>}{provenanceFromCode(result.data_class) && <ProvenanceBadge kind={provenanceFromCode(result.data_class)!} />}{result.quality && <QualityBadge value={result.quality} />}</div>}</div>
          {requestError && <ErrorState message={requestError} onRetry={() => void submit()} />}
          {!requestError && !result && <div className="scenario-empty"><h3>조건을 정하고 ‘시나리오 계산’을 누르세요</h3><p>이 격자의 관측 원단위로 계획안의 연간 에너지·탄소를 계산합니다. 근거 자료가 없으면 임의의 결과를 만들지 않습니다. 3D 배치와 용도지역 확인은 계산 전에도 바로 바뀝니다.</p></div>}
          {result && <div className={stale ? 'scenario-stale' : undefined}><PlanResult result={result} chart={chart} reporting={reporting} sceneSaved={sceneSaved === result.id} onReport={openReport} /></div>}
          {zoning && <ZoningSummary zoning={zoning} saved={!!result?.zoning_check} />}
        </section>
      </div>
    </div>
    <section className="panel optimization-panel"><div className="panel-title"><h3>도시구조 최적화</h3><span className="status-tag neutral">결정론적 계산</span></div><p className="panel-description">최소 수용 목표를 충족하는 후보를 같은 입력과 제약에서 항상 같은 순서로 탐색합니다. 대지의 용도지역이 확인되면 법적 상한(그 지역 도시계획 조례 기본 상한, 조례에 없거나 조례를 못 받은 경우 국토계획법 시행령 상한) 안의 후보만 봅니다.</p><div className="optimization-controls"><label><span>최소 세대수</span><input type="number" min="0" value={constraints.min_households} onChange={(event) => setConstraints((old) => ({ ...old, min_households: Number(event.target.value) }))} /></label><label><span>최소 인구</span><input type="number" min="0" value={constraints.min_population} onChange={(event) => setConstraints((old) => ({ ...old, min_population: Number(event.target.value) }))} /></label><button type="button" className="button secondary" onClick={() => void optimize()} disabled={optimizing}>{optimizing ? '탐색 중…' : '최적안 탐색'}</button></div>{optimization && <OptimizationResults result={optimization} onApply={(row) => setInput((old) => ({ ...old, building_count: Number(row.building_count), floors: Number(row.floors), households: Number(row.households), population: Number(row.population) }))} />}</section>
  </div>;
}

function PlanResult({ result, chart, reporting, sceneSaved, onReport }: { result: ScenarioResult; chart: ReturnType<typeof planChartOption>; reporting: boolean; sceneSaved: boolean; onReport: () => void }) {
  const plan = annualSide(result, 'scenario'); const reference = annualSide(result, 'reference');
  const savings = result.savings_pct?.carbon_kg ?? null;
  const legal = result.zoning_check?.check?.label ?? result.legal_status ?? null;
  const limits = result.zoning_check;
  if (!hasAnnual(result)) {
    return <>
      {result.total_footprint !== undefined && <PlanStrip result={result} />}
      <div className="missing-reason"><Info size={18} /><div><strong>기준 자료가 없어 추정할 수 없습니다</strong><p>{result.quality ?? '공간 매칭된 기준 에너지 또는 기준 연면적이 없습니다.'}</p></div></div>
      <details className="method-note"><summary>산정 방법과 가정</summary><p>{result.limitation ?? `${result.label ?? '원단위 기반 1차 추정'} 결과이며, 설계·인허가 수치로 사용할 수 없습니다.`}</p>{result.assumptions?.length ? <ul>{result.assumptions.map((a) => <li key={a}>{a}</li>)}</ul> : null}</details>
    </>;
  }
  return <>
    <div className="result-hero" data-testid="plan-hero">
      <div className="hero-main"><span>연간 운영탄소 (전력+가스)</span><strong>{tonnes(plan?.carbon_kg)}</strong><small>전력 {tonnes(plan?.electricity_carbon_kg)} · 가스 {tonnes(gasCarbon(plan))} (가정 계수)</small></div>
      <div className={`hero-saving ${savings !== null ? (savings > 0 ? 'good' : savings < 0 ? 'bad' : '') : ''}`}><span>기준안 대비</span><strong>{savingsText(savings)}</strong><small>{reference?.carbon_kg != null ? `같은 연면적을 효율 1.0·태양광 0으로 지으면 ${tonnes(reference.carbon_kg)}` : '기준안 값 없음'}</small></div>
      <div><span>1인당 운영탄소</span><strong>{formatMetric(result.carbon_per_person, 'kgCO₂eq', 0)}</strong><small>세대당 {formatMetric(result.carbon_per_household, 'kgCO₂eq', 0)}</small></div>
      <div><span>조례 상한 1차 확인</span><strong className={`legal ${zoningTone(legal ?? undefined)}`}>{legal ?? '판단 보류'}</strong><small>{limits?.bcr_limit != null && limits?.far_limit != null ? `상한 건폐율 ${limits.bcr_limit}% · 용적률 ${limits.far_limit}%` : '대지 위치를 지정하면 확인'}</small></div>
    </div>
    <div className="result-actions"><button type="button" className="button primary" onClick={onReport} disabled={!result.id || reporting}><FileText size={15} />{reporting ? '3D 장면 저장 중…' : sceneSaved ? '보고서 작성 (3D 장면 포함)' : '보고서 작성'}</button><small>3D 장면을 저장한 뒤 이 계획안의 검토 보고서를 엽니다.</small></div>
    {result.total_footprint !== undefined && <PlanStrip result={result} />}
    {result.baseline_estimate && <p className="estimate-note" role="note"><Info size={15} aria-hidden="true" /><span>이 격자에는 12개월 관측과 연면적이 모두 있는 지번이 없어 <b>{result.baseline_estimate.label}</b>(관측 지번 {result.baseline_estimate.parcels}곳, 연면적 {formatMetric(result.baseline_estimate.area_m2, 'm²')})로 추정했습니다.</span></p>}
    <table className="energy-table"><thead><tr><th>연간</th><th className="num">계획안</th><th className="num">기준안</th><th className="num">절감</th></tr></thead><tbody>
      <tr><th>전력</th><td className="num">{formatMetric(plan?.electricity_kwh, 'kWh')}</td><td className="num">{formatMetric(reference?.electricity_kwh, 'kWh')}</td><td className="num">{savingsText(result.savings_pct?.electricity_kwh)}</td></tr>
      <tr><th>가스</th><td className="num">{formatMetric(plan?.gas_kwh, 'kWh')}</td><td className="num">{formatMetric(reference?.gas_kwh, 'kWh')}</td><td className="num">{savingsText(result.savings_pct?.gas_kwh)}</td></tr>
      <tr><th>전력 탄소</th><td className="num">{tonnes(plan?.electricity_carbon_kg)}</td><td className="num">{tonnes(reference?.electricity_carbon_kg)}</td><td className="num"></td></tr>
      <tr><th>가스 탄소 (가정 계수)</th><td className="num">{tonnes(gasCarbon(plan))}</td><td className="num">{tonnes(gasCarbon(reference))}</td><td className="num"></td></tr>
    </tbody></table>
    {chart && <Chart option={chart.option} height={250} ariaLabel="계획안과 기준안의 월별 운영탄소" />}
    <details className="method-note"><summary>산정 방법과 가정</summary><p>{methodText(result)}</p><p>{result.limitation ?? '원단위 기반 1차 추정이며, 설계·인허가 수치로 사용할 수 없습니다.'}</p>{result.assumptions?.length ? <ul>{result.assumptions.map((a) => <li key={a}>{a}</li>)}</ul> : null}</details>
  </>;
}

function PlanStrip({ result }: { result: ScenarioResult }) {
  const zc = result.zoning_check;
  return <div className="calculation-strip"><div><span>연면적</span><strong>{formatMetric(result.gross_floor_area, 'm²')}</strong></div><div><span>용적률{zc?.far_limit != null ? ` (상한 ${zc.far_limit}%)` : ''}</span><strong>{formatMetric(result.far, '%', 1)}</strong></div><div><span>건폐율{zc?.bcr_limit != null ? ` (상한 ${zc.bcr_limit}%)` : ''}</span><strong>{formatMetric(result.bcr, '%', 1)}</strong></div><div><span>건축면적 합계</span><strong>{formatMetric(result.total_footprint, 'm²')}</strong></div></div>;
}

function OptimizationResults({ result, onApply }: { result: OptimizationResult; onApply: (row: Record<string, unknown>) => void }) { const rows = result.alternatives ?? result.candidates ?? []; return <div className="optimization-results"><div className="optimization-status">{result.status && <QualityBadge value={result.status} />}<strong>{result.legal_status ?? 'ENERGY_OPTIMAL · 법적 상한 미확정'}</strong><p>{result.explanation ?? result.reason ?? '서버가 반환한 제약 충족 후보를 목적함수 순으로 표시합니다.'}</p></div>{rows.length ? <div className="alternative-grid">{rows.slice(0, 5).map((row, index) => <article key={String(row.id ?? index)}><span>{String(row.label ?? row.objective ?? `대안 ${index + 1}`)}</span><h4>{row.floors === null || row.floors === undefined ? '층수 자료 없음' : `${row.floors}층 · ${row.building_count ?? '—'}동`}</h4><dl>{OPTIMIZATION_FIELDS.map(([key, label, unit, digits]) => <div key={key}><dt>{label}</dt><dd>{typeof row[key] === 'number' ? formatMetric(row[key] as number, unit, digits) : '자료 없음'}</dd></div>)}</dl>{typeof row.floors === 'number' && typeof row.building_count === 'number' && <button type="button" className="button ghost small" onClick={() => onApply(row)}>이 조건을 입력에 적용</button>}</article>)}</div> : <EmptyState title="제약을 충족하는 후보가 없습니다" />}{result.limitations?.length ? <ul className="optimization-limitations">{result.limitations.map((item) => <li key={item}>{item}</li>)}</ul> : null}</div>; }
const OPTIMIZATION_FIELDS: Array<[string, string, string, number]> = [['far', '용적률', '%', 1], ['bcr', '건폐율', '%', 1], ['households', '세대수', '세대', 0], ['population', '인구', '명', 0], ['annual_electricity_kwh', '연간 전력', 'kWh', 0], ['annual_carbon_kg', '연간 전체 탄소', 'kgCO₂eq', 0]];
