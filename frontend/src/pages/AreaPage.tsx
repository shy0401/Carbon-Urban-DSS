import { Download, FileText, Info, Pause, Play, RotateCcw, Undo2 } from 'lucide-react';
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { AreaMap } from '../components/area/AreaMap';
import { BeforeAfterChart, DevelopmentChart, EffortBars, EffortCurve, ElectricityChart, RegisterChart, WeatherYearsChart } from '../components/area/AreaCharts';
import { MetricCard } from '../components/MetricCard';
import { PageHeader } from '../components/PageHeader';
import { ProvenanceBadge } from '../components/ProvenanceBadge';
import { SgisGridSummaryView } from '../components/SgisGridPanel';
import { EmptyState, ErrorState, LoadingState } from '../components/Status';
import { useAnalysisScope } from '../hooks/useAnalysisScope';
import { useApi } from '../hooks/useApi';
import { api } from '../lib/api';
import { at, buildSpec, EFFORT_BASIS_LABEL, effortHeadline, eventYears, MODE_LABEL, planBody, plannedArea, REPORT_MODE_LABEL, type AreaAnalysis, type AreaMode, type AreaOptions, type AreaReport, type AreaSpec, type BeforeAfter, type EffortBasis, type EffortResult, type PlanState } from '../lib/area';
import { formatDate, formatMetric } from '../lib/format';

const YEARS = Array.from({ length: 17 }, (_, i) => 2010 + i);
/** 예시값(실제 계획이 아님): 화면을 처음 열었을 때 계산이 돌아가도록 채워 둔다. */
const DEFAULT_PLAN: PlanState = { method: 'area', added_floor_area_m2: 50000, floors: 20, building_count: 5, footprint_per_building: 800, removed_floor_area_m2: 0 };
const DEFAULT_TARGET = 40;
const MODES: AreaMode[] = ['admin', 'circle', 'polygon', 'zone', 'grid'];
const DATASET_LABEL: Record<string, string> = { sgis: 'SGIS 인구·가구', kma_asos: '기상청 ASOS', kapt_energy: 'K-apt 단지 에너지', energy: '건축HUB 지번 에너지', vworld_zoning: 'VWorld 용도지역', vworld_buildings: 'VWorld 건물', vworld_cadastral: 'VWorld 연속지적', building_register: '건축물대장', sgis_grid_500m: 'SGIS 500m 격자 경계' };

interface CollectionStatus { items: Record<string, { status: string; at?: string; reason?: string }>; runs: Array<{ started_at: string; finished_at?: string; from: number; to: number }>; summary: Record<string, Record<string, number>> }

export function AreaPage() {
  const { region, regionQuery } = useAnalysisScope();
  const options = useApi<AreaOptions>(`/areas/options${regionQuery.replace('&', '?')}`);
  const collection = useApi<CollectionStatus>('/areas/collection');
  const [mode, setMode] = useState<AreaMode>('admin');
  const [adminCode, setAdminCode] = useState('');
  const [category, setCategory] = useState('');
  const [center, setCenter] = useState<[number, number] | null>(null);
  const [radius, setRadius] = useState(1000);
  const [vertices, setVertices] = useState<Array<[number, number]>>([]);
  const [fromYear, setFromYear] = useState(2015);
  const [toYear, setToYear] = useState(2025);
  const [eventYear, setEventYear] = useState<number | null>(null);
  const [windowSize, setWindowSize] = useState(3);
  const [plan, setPlan] = useState<PlanState>(DEFAULT_PLAN);
  const [target, setTarget] = useState(DEFAULT_TARGET);
  const [pvYield, setPvYield] = useState('');
  const [effortBasis, setEffortBasis] = useState<EffortBasis>('apartments');
  const [analysis, setAnalysis] = useState<AreaAnalysis | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [slider, setSlider] = useState(2025);
  const [playing, setPlaying] = useState(false);
  const lastSpec = useRef<AreaSpec | null>(null);
  const revision = useRef(0);
  const started = useRef(false);

  // 처음 열 때: 에코시티 개발이 있는 송천1동(없으면 목록 첫 동)과 가장 넓은 용도지역을 고른다.
  useEffect(() => {
    const o = options.data; if (!o) return;
    setAdminCode((old) => old || (o.admin.find((a) => a.name.includes('송천1동')) ?? o.admin[0])?.code || '');
    setCategory((old) => old || o.zones.find((z) => z.category === 'COMMERCIAL')?.category || o.zones[0]?.category || '');
  }, [options.data]);

  const run = useCallback(async (spec: AreaSpec | string) => {
    if (typeof spec === 'string') { setError(spec); return; }
    if (fromYear > toYear) { setError('시작 연도가 끝 연도보다 늦습니다.'); return; }
    lastSpec.current = spec;
    const id = ++revision.current;
    setRunning(true); setError(null);
    const pv = Number(pvYield);
    const body = { area: spec, region, from_year: fromYear, to_year: toYear, event_year: eventYear, window: windowSize, plan: planBody(plan), target_pct: target, pv_yield_kwh_per_kw: pvYield && pv > 0 ? pv : null, effort_basis: effortBasis };
    try {
      const result = await api<AreaAnalysis>('/areas/analyze', { method: 'POST', body: JSON.stringify(body) });
      if (id !== revision.current) return;
      setAnalysis(result);
      setSlider((s) => Math.min(Math.max(s, result.history.years[0]), result.history.years[result.history.years.length - 1]));
    } catch (reason) {
      if (id === revision.current) setError(reason instanceof Error ? reason.message : '분석에 실패했습니다.');
    } finally {
      if (id === revision.current) setRunning(false);
    }
  }, [fromYear, toYear, eventYear, windowSize, plan, target, pvYield, effortBasis, region]);
  const runRef = useRef(run); runRef.current = run;
  // Another region: its 행정동, zones and grids are different, so start over there.
  const shownRegion = useRef(region);
  useEffect(() => {
    if (shownRegion.current === region) return;
    shownRegion.current = region;
    revision.current++; lastSpec.current = null; started.current = false;
    setAnalysis(null); setAdminCode(''); setCategory(''); setCenter(null); setVertices([]); setError(null);
  }, [region]);

  const specFor = useCallback((m: AreaMode, over: Partial<{ code: string; category: string; center: [number, number]; vertices: Array<[number, number]> }> = {}) =>
    buildSpec(m, { code: over.code ?? adminCode, category: over.category ?? category, grid: options.data?.default_grid, center: over.center ?? center, radius, vertices: over.vertices ?? vertices }), [adminCode, category, options.data, center, radius, vertices]);

  // First analysis once the defaults are known (declared before the region reset above uses it).

  useEffect(() => { if (!started.current && adminCode && options.data) { started.current = true; void runRef.current({ type: 'admin', code: adminCode }); } }, [adminCode, options.data]);

  // Parameter changes re-run the last area (debounced) — the engine recomputes every number.
  useEffect(() => {
    if (!lastSpec.current) return;
    const timer = window.setTimeout(() => { if (lastSpec.current) void runRef.current(lastSpec.current); }, 450);
    return () => window.clearTimeout(timer);
  }, [fromYear, toYear, eventYear, windowSize, plan, target, pvYield, effortBasis]);
  useEffect(() => {
    if (mode !== 'circle' || !center || lastSpec.current?.type !== 'circle') return;
    const timer = window.setTimeout(() => void runRef.current(specFor('circle')), 450);
    return () => window.clearTimeout(timer);
  }, [radius]); // eslint-disable-line react-hooks/exhaustive-deps

  // Year slider playback
  const years = analysis?.history.years ?? [];
  useEffect(() => {
    if (!playing || !years.length) return;
    const timer = window.setInterval(() => setSlider((s) => { if (s >= years[years.length - 1]) { setPlaying(false); return s; } return s + 1; }), 900);
    return () => window.clearInterval(timer);
  }, [playing, years]);

  const pickAdmin = (code: string) => { setAdminCode(code); if (mode === 'admin') void run({ type: 'admin', code }); };
  const pickPoint = (point: [number, number]) => {
    if (mode === 'circle') { setCenter(point); void run(specFor('circle', { center: point })); }
    if (mode === 'polygon') setVertices((v) => [...v, point]);
  };
  const changeMode = (next: AreaMode) => {
    setMode(next); setError(null);
    if (next === 'admin' && adminCode) void run({ type: 'admin', code: adminCode });
    if (next === 'zone' && category) void run({ type: 'zone', category });
    if (next === 'grid') void run(specFor('grid'));
  };

  const activeEvent = analysis?.before_after.available ? analysis.before_after.event_year ?? null : null;

  if (options.loading) return <div className="page"><LoadingState label="지역 목록을 불러오는 중입니다" /></div>;
  if (options.error || !options.data) return <div className="page"><ErrorState message={options.error} onRetry={options.reload} /></div>;
  const o = options.data;

  return <div className="page area-page" data-testid="area-page">
    <PageHeader title="지역 개발 시뮬레이션" description="행정동·반경·직접 그린 구역·용도지역 어디든 골라 과거와 현재를 비교하고, 개발 전후 영향과 앞으로 필요한 감축 노력을 계산합니다." action={<div className="badge-row"><span className="badge warn"><Info size={13} />운영 단계 1차 추정</span><a className="button ghost small" href="/guide#area">사용 방법</a></div>} />

    <section className="panel area-controls" aria-label="분석 구역 선택">
      <div className="area-modes" role="tablist" aria-label="구역 선택 방식">
        {MODES.map((m) => <button key={m} role="tab" aria-selected={mode === m} onClick={() => changeMode(m)} disabled={m === 'grid' && !o.default_grid}>{MODE_LABEL[m]}</button>)}
      </div>
      <div className="area-control-row">
        {mode === 'admin' && <label className="area-select"><span>행정동 ({o.admin.length}개)</span><select value={adminCode} onChange={(e) => pickAdmin(e.target.value)}>{o.admin.map((a) => <option key={a.code} value={a.code}>{a.name}</option>)}</select></label>}
        {mode === 'zone' && <label className="area-select"><span>용도지역 (주 용도 격자 묶음)</span><select value={category} onChange={(e) => { setCategory(e.target.value); void run({ type: 'zone', category: e.target.value }); }}>{o.zones.map((z) => <option key={z.category} value={z.category}>{z.label} · 격자 {z.grids}개</option>)}</select></label>}
        {mode === 'circle' && <><label className="area-select narrow"><span>반경</span><div className="with-unit"><input type="number" min={100} max={5000} step={100} value={radius} onChange={(e) => setRadius(Number(e.target.value))} /><em>m</em></div></label><p className="area-hint">{center ? `중심 ${center[1].toFixed(4)}, ${center[0].toFixed(4)} — 지도를 다시 누르면 옮깁니다.` : '지도에서 개발 예정지 중심을 누르세요.'}</p></>}
        {mode === 'polygon' && <><p className="area-hint">지도를 눌러 꼭짓점을 찍습니다 ({vertices.length}개).</p><button className="button small" onClick={() => setVertices((v) => v.slice(0, -1))} disabled={!vertices.length}><Undo2 size={14} />마지막 점 취소</button><button className="button small" onClick={() => setVertices([])} disabled={!vertices.length}><RotateCcw size={14} />지우기</button><button className="button small primary" onClick={() => void run(specFor('polygon'))} disabled={vertices.length < 3}>구역 확정·분석</button></>}
        {mode === 'grid' && <p className="area-hint">예비 선정 격자 <code>{o.default_grid}</code> (500m).</p>}
        <label className="area-select narrow"><span>시작 연도</span><select value={fromYear} onChange={(e) => setFromYear(Number(e.target.value))}>{YEARS.map((y) => <option key={y} value={y}>{y}</option>)}</select></label>
        <label className="area-select narrow"><span>끝 연도</span><select value={toYear} onChange={(e) => setToYear(Number(e.target.value))}>{YEARS.map((y) => <option key={y} value={y}>{y}</option>)}</select></label>
        {running && <span className="area-running" role="status"><span className="spinner" aria-hidden="true" />계산 중</span>}
      </div>
      {error && <p className="form-error" role="alert">{error}</p>}
      <CoverageStrip analysis={analysis} collection={collection.data} regionName={region ? (options.data?.region?.short_name ?? null) : null} />
    </section>

    <div className="area-workspace">
      <div className="area-map-stage">
        <AreaMap adminGeojson={o.admin_geojson} mode={mode} adminCode={adminCode} center={center} radius={radius} vertices={vertices} analysis={analysis} sliderYear={slider} eventYear={activeEvent} onPickAdmin={pickAdmin} onPickPoint={pickPoint} />
      </div>
      {analysis ? <YearPanel analysis={analysis} year={slider} setYear={setSlider} playing={playing} setPlaying={setPlaying} eventYear={activeEvent} /> : <div className="panel"><EmptyState title={running ? '계산 중입니다' : '구역을 고르세요'} description="행정동을 고르거나 지도에서 위치를 누르면 계산합니다." /></div>}
    </div>

    {analysis && <>
      <div className="section-label"><h2>과거와 현재</h2><span>{analysis.history.years[0]}~{analysis.history.years[analysis.history.years.length - 1]} · {analysis.history.area.label}</span></div>
      <div className="content-grid two-up area-charts">
        <section className="panel"><div className="panel-title"><h3>연도별 전력 사용량</h3><div className="badge-row"><ProvenanceBadge kind="observed" detail="12개월 완전 지번" /><ProvenanceBadge kind="estimated" /></div></div><ElectricityChart history={analysis.history} eventYear={activeEvent} /><p className="muted">막대는 12개월이 모두 관측된 단지만 더한 값을 단지 준공 시기별로 나눈 것입니다. 점선은 그 해까지 준공된 단지 연면적 × {analysis.history.region_label ?? '전주'} 관측 원단위로 낸 추정입니다. 전력은 모든 연도를 K-apt 관리비 전력 한 출처로 셉니다(2024년부터 있는 건축HUB 계측값은 같은 단지에서 K-apt보다 커서, 섞으면 사용량이 늘어난 것처럼 보입니다). 건축HUB 값은 아래 '건물 전체 에너지'에 따로 둡니다.</p></section>
        <section className="panel"><div className="panel-title"><h3>개발 이력 (사용승인 세대)</h3><ProvenanceBadge kind="computed" detail="K-apt 사용승인일" /></div><DevelopmentChart history={analysis.history} eventYear={activeEvent} /><p className="muted">호박색 막대가 전후 비교에 쓰는 개발 연도입니다. 막대에 마우스를 올리면 단지명이 보입니다.</p></section>
        <section className="panel"><div className="panel-title"><h3>기상 (난방도일·냉방도일)</h3><ProvenanceBadge kind={region ? 'estimated' : 'observed'} detail={region ? 'ERA5-Land 재분석' : 'ASOS 전주'} /></div><WeatherYearsChart history={analysis.history} /><p className="muted">12개월이 모두 있는 해만 그립니다. 전후 사용량 차이의 일부는 기상 차이일 수 있습니다.</p></section>
        <PopulationPanel analysis={analysis} />
        <RegisterPanel analysis={analysis} eventYear={activeEvent} />
      </div>
      <BuildingEnergyPanel analysis={analysis} />
      <SgisAreaPanel analysis={analysis} />

      <div className="section-label"><h2>개발 전후 영향</h2><span>개발 연도는 전환기라 제외하고 앞뒤 {windowSize}년 평균을 비교합니다</span></div>
      <BeforeAfterPanel comparison={analysis.before_after} candidates={eventYears(analysis.history)} eventYear={eventYear} setEventYear={setEventYear} windowSize={windowSize} setWindowSize={setWindowSize} />

      <div className="section-label"><h2>미래 개발과 감축 노력</h2><span>목표 감축률을 넣으면 필요한 노력을 계산합니다</span></div>
      <EffortPanel effort={analysis.effort} plan={plan} setPlan={setPlan} target={target} setTarget={setTarget} pvYield={pvYield} setPvYield={setPvYield} basis={effortBasis} setBasis={setEffortBasis} />

      <div className="section-label"><h2>보고서</h2><span>계산 엔진의 근거 문장으로 작성하고, 로컬 AI 문장은 숫자 검증을 통과할 때만 씁니다</span></div>
      <ReportPanel request={() => ({ area: lastSpec.current, region, from_year: fromYear, to_year: toYear, event_year: eventYear, window: windowSize, plan: planBody(plan), target_pct: target, pv_yield_kwh_per_kw: pvYield && Number(pvYield) > 0 ? Number(pvYield) : null })} label={analysis.history.area.label} />
    </>}
  </div>;
}

function CoverageStrip({ analysis, collection, regionName }: { analysis: AreaAnalysis | null; collection: CollectionStatus | null; regionName?: string | null }) {
  const cov = analysis?.history.coverage;
  const summary = collection?.summary ?? {};
  const datasets = Object.keys(summary);
  const list = (ys: number[] | undefined) => (ys && ys.length ? ys.join(', ') : '없음');
  return <div className="area-coverage">
    {cov && <dl>
      <div><dt>전력 관측 연도</dt><dd>{list(cov.energy_years)}</dd></div>
      <div><dt>기상 12개월 연도</dt><dd>{list(cov.weather_years)}</dd></div>
      <div><dt>인구 연도</dt><dd>{list(cov.population_years)}</dd></div>
      <div><dt>구역</dt><dd>격자 {cov.grid_count}개 · 단지 {cov.complex_count}곳</dd></div>
    </dl>}
    <p className="area-collect">{regionName
      ? <>이 지역({regionName})은 지역 준비 때 분석연도 자료만 받았습니다(과거 연도 일괄 수집은 전주시 범위). 단계별 상태는 <Link to="/regions">전국 지역</Link>에서 봅니다.</>
      : datasets.length
      ? <><span className="area-collect-title">과거 수집 진행 (연도·항목 수)</span><span className="area-collect-list">{datasets.map((d) => <span key={d} className="area-collect-item"><b>{DATASET_LABEL[d] ?? d}</b>{Object.entries(summary[d]).map(([st, n]) => <em key={st} className={`st-${st.toLowerCase()}`}>{statusLabel(st)} {n}</em>)}</span>)}</span></>
      : <>과거 연도 자료는 아직 수집하지 않았습니다. <a href="/data#collect-missing">수집 데이터 → 빠진 자료 전부 수집</a> 버튼을 누르거나 PC에서 <code>scripts\dss.cmd CollectAll</code>을 실행하면 채워집니다 (일일 한도에 걸리면 다음 날 자동으로 이어서).</>}</p>
  </div>;
}

function statusLabel(status: string) { return ({ DONE: '완료', NOT_PUBLISHED: '미공개', PARTIAL: '일부', FAILED: '실패', BLOCKED: '보류', TODO: '대기', RETRY: '재시도', WAITING: '대기' } as Record<string, string>)[status] ?? status; }

function YearPanel({ analysis, year, setYear, playing, setPlaying, eventYear }: { analysis: AreaAnalysis; year: number; setYear: (y: number) => void; playing: boolean; setPlaying: (p: boolean) => void; eventYear: number | null }) {
  const h = analysis.history;
  const first = h.years[0]; const last = h.years[h.years.length - 1];
  const stock = at(h.stock, year); const ev = at(h.events, year); const e = at(h.energy, year); const pop = at(h.population, year);
  const elec = e?.electricity;
  const collected = h.coverage.energy_years.length > 0;
  return <section className="panel area-year" aria-label="연도별 상태">
    <div className="panel-title"><h3>{h.area.label}</h3><small>{h.area.method}</small></div>
    <div className="area-slider">
      <button className="button small" onClick={() => { if (!playing && year >= last) setYear(first); setPlaying(!playing); }} aria-label={playing ? '재생 멈춤' : '연도 재생'}>{playing ? <Pause size={14} /> : <Play size={14} />}{playing ? '멈춤' : '재생'}</button>
      <input type="range" min={first} max={last} step={1} value={year} onChange={(ev2) => { setPlaying(false); setYear(Number(ev2.target.value)); }} aria-label="시점 연도" />
      <strong>{year}년{year === eventYear ? ' · 개발 연도' : ''}</strong>
    </div>
    <div className="metric-grid dense">
      <MetricCard dense title="준공 누적 단지" value={stock?.complexes} unit="곳" provenance="computed" basis="K-apt 사용승인일 기준" />
      <MetricCard dense title="준공 누적 세대" value={stock?.households} unit="세대" provenance="computed" />
      <MetricCard dense title="연면적 확인 단지 합계" value={stock?.gfa_m2} unit="m²" provenance="computed" basis={stock?.gfa_excluded ? `연면적 이상 ${stock.gfa_excluded}곳 제외` : undefined} />
      <MetricCard dense title="이 해 사용승인" value={ev?.households ?? 0} unit="세대" provenance="computed" basis={ev?.complexes ? `${ev.complexes}개 단지` : '없음'} />
      <MetricCard dense title="전력 관측" value={elec?.kwh} unit="kWh" provenance="observed" basis={elec?.kwh != null ? `12개월 관측 ${elec.complete_parcels}곳` : undefined} missingReason={collected ? '12개월이 모두 관측된 지번이 없습니다.' : '과거 전력을 아직 수집하지 않았습니다.'} />
      <MetricCard dense title="전력 추정" value={e?.estimated?.kwh} unit="kWh" provenance="estimated" basis={`연면적 × ${h.region_label ?? '전주'} 원단위`} missingReason="연면적이 확인된 단지가 없습니다." />
      <MetricCard dense title="전력 탄소 (관측)" value={e?.electricity_carbon_kgco2eq} unit="kgCO₂eq" provenance="computed" basis={h.factor.electricity ? `계수 ${h.factor.electricity}` : undefined} missingReason="관측 전력이 없어 계산하지 않았습니다." />
      <MetricCard dense title="인구" value={pop?.population} unit="명" provenance="observed" basis={pop?.basis} missingReason={`${year}년 SGIS 인구를 아직 수집하지 않았습니다.`} />
    </div>
    <p className="muted">{h.factor_basis}</p>
  </section>;
}

function RegisterPanel({ analysis, eventYear }: { analysis: AreaAnalysis; eventYear: number | null }) {
  const reg = analysis.history.register;
  return <section className="panel area-register"><div className="panel-title"><h3>모든 건물의 개발 이력 (건축물대장)</h3><ProvenanceBadge kind="observed" detail="건축물대장 표제부" /></div>
    {reg?.linked_in_area ? <>
      <RegisterChart history={analysis.history} eventYear={eventYear} />
      <p className="muted">구역 격자 안 건물 {formatMetric(reg.linked_in_area)}동의 사용승인일 기준입니다(아파트 외 상가·업무·공공 건물 포함).{reg.unknown_year ? ` 사용승인일을 읽을 수 없는 ${formatMetric(reg.unknown_year)}동은 뺐습니다.` : ''} 연면적이 비어 있는 건물은 0이 아니라 합계에서 빠집니다.</p>
    </> : <EmptyState title={reg?.available ? '이 구역에 연결된 대장 건물이 없습니다' : '건축물대장을 아직 수집하지 않았습니다'} description={reg?.available ? '대장 건물의 위치(격자)는 연속지적 전체 수집 뒤 연결됩니다.' : "수집 데이터 화면의 '빠진 자료 전부 수집'으로 받을 수 있습니다 (건축물대장 활용신청 승인 필요)."} />}
  </section>;
}

/** 구역 격자 안 건축HUB 계측 건물 전체(전주 2020-). 공동주택 시계열과 따로 둔다. */
function BuildingEnergyPanel({ analysis }: { analysis: AreaAnalysis }) {
  const be = analysis.history.building_energy;
  const years = be ? Object.values(be.years).sort((a, b) => a.year - b.year) : [];
  return <section className="panel area-building-energy" aria-label="건물 전체 에너지">
    <div className="panel-title"><h3>건물 전체 에너지 (건축HUB 전 지번)</h3><ProvenanceBadge kind="observed" detail="12개월 계측 지번" /></div>
    {years.length ? <><div className="table-wrap"><table>
      <thead><tr><th>연도</th><th className="num">계측 지번</th><th className="num">전력 kWh</th><th className="num">가스 kWh</th><th className="num">전력 원단위 kWh/m²</th><th className="num">전력 탄소 tCO₂eq</th></tr></thead>
      <tbody>{years.map((v) => <tr key={v.year}><td>{v.year}{v.complete === false && <small className="status-tag warn">수집 중</small>}{v.provider_gap && <small className="status-tag warn" title={v.provider_gap}>일부 결측·비교 제외</small>}</td><td className="num">{formatMetric(v.parcels)}<small> (12개월 {formatMetric(v.electricity_complete)})</small></td><td className="num">{formatMetric(v.electricity_kwh)}</td><td className="num">{formatMetric(v.gas_kwh)}</td><td className="num">{formatMetric(v.kwh_per_m2, '', 1)}</td><td className="num">{v.electricity_carbon_kgco2eq === null ? '자료 없음' : formatMetric(v.electricity_carbon_kgco2eq / 1000, '', 1)}</td></tr>)}</tbody>
    </table></div>
    <p className="muted">상가·업무·학교·대형 공동주택 등 건축HUB가 계측하는 모든 지번의 합계입니다(연속지적 대표점으로 격자 배치). 단독주택, 200세대 미만 공동주택, 산업·수송용은 제공 범위 밖이라 빠집니다. 건축HUB는 2020년 1월분부터 있습니다(전주 2020~, 수원·완주 2024~). {years.filter((v) => v.provider_gap).map((v) => `${v.year}년: ${v.provider_gap}. `).join('')}원단위는 같은 필지의 건축물대장 연면적 기준입니다.</p></>
      : <EmptyState title="이 구역의 건물 전체 에너지가 아직 없습니다" description="건축HUB 전 지번 수집(2020년~)이 끝나면 채워집니다. 구역 격자 안에 계측 지번이 없을 수도 있습니다(단독주택 위주)." />}
  </section>;
}

/** 구역이 걸친 SGIS 1km 격자 전체의 합(관측)과, 면적 비례로 나눈 참고값(추정)을 나란히 둔다. */
function SgisAreaPanel({ analysis }: { analysis: AreaAnalysis }) {
  const sg = analysis.history.sgis_grid;
  return <section className="panel area-sgis" aria-label="지역 특성 (SGIS 1km 격자)">
    <div className="panel-title"><h3>지역 특성 (SGIS 1km 격자{sg ? ` ${sg.year}년` : ''})</h3><div className="badge-row"><ProvenanceBadge kind="observed" detail="1km 격자 합계" />{sg?.overlap && <ProvenanceBadge kind="estimated" detail="구역 면적 비례" />}</div></div>
    {!sg ? <EmptyState title="SGIS 격자 통계를 아직 가져오지 않았습니다" description="공공데이터포털 'SGIS 격자 통계 및 경계' 파일을 잘라 두면 API 시작 때 자동으로 들어옵니다 (사용 방법 → SGIS 격자 통계)." />
      : !sg.overlap ? <EmptyState title="이 구역이 걸친 1km 격자에는 공표된 통계가 없습니다" description="인구·사업체가 없거나 비공개인 격자이며 0이 아닙니다." />
      : <SgisGridSummaryView summary={sg.overlap}
          scope={<>구역이 걸친 1km 격자 <b>{sg.cells}개</b>(통계 있는 격자 {sg.cells_with_stats}개) 전체의 합계입니다. {sg.coverage_pct !== null && sg.coverage_pct < 99.9 ? <>구역은 이 격자 면적의 <b>{sg.coverage_pct.toFixed(1)}%</b>라 합계는 구역보다 넓은 범위입니다.</> : '구역이 이 격자들과 같은 범위입니다.'}</>}
          extra={sg.coverage_pct !== null && sg.coverage_pct < 99.9 ? <div className="is-estimated"><dt>구역 인구 (면적 비례 추정)</dt><dd>{formatMetric(sg.estimated.population, '명')}<small>{sg.estimated.basis}</small></dd></div> : undefined} />}
  </section>;
}

function PopulationPanel({ analysis }: { analysis: AreaAnalysis }) {
  const h = analysis.history;
  const rows = h.years.map((y) => ({ year: y, p: at(h.population, y) })).filter((r) => r.p?.population != null);
  return <section className="panel"><div className="panel-title"><h3>인구·가구 (행정동)</h3><ProvenanceBadge kind="observed" detail="SGIS" /></div>
    {rows.length ? <div className="table-wrap"><table><thead><tr><th>연도</th><th className="num">인구</th><th className="num">가구</th><th>기준</th></tr></thead><tbody>{rows.map(({ year, p }) => <tr key={year}><td>{year}</td><td className="num">{formatMetric(p?.population)}</td><td className="num">{formatMetric(p?.households)}</td><td><small>{p?.basis}</small></td></tr>)}</tbody></table></div>
      : <EmptyState title="인구 자료가 없습니다" description="이 구역과 겹치는 행정동의 SGIS 인구를 아직 수집하지 않았습니다." />}
    <p className="muted">{h.area.admin_exact ? '선택한 행정동의 값입니다.' : '구역과 겹치는 행정동 전체 값입니다. 격자·반경으로 나누어 배분하지 않았습니다.'} 수집 연도: {h.coverage.population_years.join(', ') || '없음'}</p>
  </section>;
}

/** 한 줄 수치. signed면 증감이라 양수에 +를 붙인다. 값이 없으면 0이 아니라 "자료 없음". */
function Figure({ label, value, unit, digits = 0, note, signed = false }: { label: string; value: number | null | undefined; unit: string; digits?: number; note?: ReactNode; signed?: boolean }) {
  const missing = value === null || value === undefined;
  return <div className={missing ? 'is-missing' : undefined}><dt>{label}</dt><dd>{missing ? '자료 없음' : `${signed && value > 0 ? '+' : ''}${formatMetric(value, unit, digits)}`}{note && <small>{note}</small>}</dd></div>;
}

function BeforeAfterPanel({ comparison, candidates, eventYear, setEventYear, windowSize, setWindowSize }: { comparison: BeforeAfter; candidates: number[]; eventYear: number | null; setEventYear: (y: number | null) => void; windowSize: number; setWindowSize: (w: number) => void }) {
  const m = comparison.metrics;
  return <section className="panel area-before-after">
    <div className="area-inline-controls">
      <label className="area-select"><span>개발 연도</span><select value={eventYear ?? ''} onChange={(e) => setEventYear(e.target.value ? Number(e.target.value) : null)}><option value="">자동 (세대 증가가 가장 큰 해{comparison.available && !eventYear ? ` · ${comparison.event_year}` : ''})</option>{candidates.map((y) => <option key={y} value={y}>{y}</option>)}</select></label>
      <label className="area-select narrow"><span>비교 기간</span><select value={windowSize} onChange={(e) => setWindowSize(Number(e.target.value))}>{[1, 2, 3, 4, 5].map((w) => <option key={w} value={w}>앞뒤 {w}년</option>)}</select></label>
    </div>
    {!comparison.available ? <EmptyState title="비교할 개발이 없습니다" description={comparison.reason} /> : <>
      <p className="area-event"><b>{comparison.event_year}년</b> 사용승인 {comparison.event?.complexes}개 단지 · {formatMetric(comparison.event?.households)}세대 · 연면적 {formatMetric(comparison.event?.gfa_m2, 'm²')}<small>{(comparison.event?.names ?? []).join(', ')}</small></p>
      <div className="area-split">
        <BeforeAfterChart comparison={comparison} />
        <div>
          <h4 className="area-subhead">관측 <ProvenanceBadge kind="observed" /></h4>
          <dl className="area-figures">
            <Figure label="전력 연평균 변화" value={m?.electricity.total_change_pct} unit="%" digits={1} signed />
            <Figure label="기존 단지만의 변화" value={m?.electricity.existing_change_pct} unit="%" digits={1} note={m?.electricity.existing_complexes ? `전후 모든 해에 보고한 같은 단지 ${m.electricity.existing_complexes}곳끼리` : '같은 단지끼리 비교'} signed />
            <Figure label="개발 후 신규 단지 비중" value={m?.electricity.new_share_pct} unit="%" digits={1} />
          </dl>
          <h4 className="area-subhead">추정 <ProvenanceBadge kind="estimated" /></h4>
          <dl className="area-figures">
            <Figure label="이 개발로 늘어난 연면적" value={m?.estimated?.added_gfa_m2} unit="m²" />
            <Figure label="이 개발만의 전력 증가" value={m?.estimated?.event_added_kwh} unit="kWh/년" note={m?.estimated?.event_change_pct != null ? `직전 재고 대비 +${m.estimated.event_change_pct}%` : undefined} />
            <Figure label="전후 추정 변화 (다른 해 개발 포함)" value={m?.estimated?.change_pct} unit="%" digits={1} signed />
          </dl>
          <h4 className="area-subhead">맥락</h4>
          <dl className="area-figures">
            <Figure label="난방도일 전 → 후" value={comparison.weather?.before_hdd} unit="°C·일" note={comparison.weather?.after_hdd != null ? `→ ${formatMetric(comparison.weather.after_hdd, '°C·일')}` : undefined} />
            <Figure label="냉방도일 전 → 후" value={comparison.weather?.before_cdd} unit="°C·일" note={comparison.weather?.after_cdd != null ? `→ ${formatMetric(comparison.weather.after_cdd, '°C·일')}` : undefined} />
            <Figure label="인구 전 → 후" value={comparison.population?.before} unit="명" note={comparison.population?.after != null ? `→ ${formatMetric(comparison.population.after, '명')}` : comparison.population?.basis} />
          </dl>
        </div>
      </div>
      {comparison.gaps?.length ? <ul className="area-gaps">{comparison.gaps.map((g) => <li key={g}>{g}</li>)}</ul> : null}
    </>}
  </section>;
}

function EffortPanel({ effort, plan, setPlan, target, setTarget, pvYield, setPvYield, basis, setBasis }: { effort: EffortResult | null; plan: PlanState; setPlan: (p: PlanState) => void; target: number; setTarget: (t: number) => void; pvYield: string; setPvYield: (v: string) => void; basis: EffortBasis; setBasis: (b: EffortBasis) => void }) {
  const headline = effortHeadline(effort);
  const num = (key: keyof PlanState, label: string, unit: string, step = 1) => <label className="field" key={key}><span>{label}</span><div><input type="number" min={0} step={step} value={plan[key] as number} onChange={(e) => setPlan({ ...plan, [key]: Math.max(0, Number(e.target.value)) })} /><em>{unit}</em></div></label>;
  const o = effort?.options;
  const t = (v: number | undefined | null) => (v == null ? null : v / 1000);
  return <section className="panel area-effort">
    <div className="area-effort-layout">
      <div className="area-effort-form">
        <div className="panel-title"><h3>계획 조건</h3><span className="status-tag neutral">예시값</span></div>
        <div className="area-modes small" role="tablist" aria-label="계획 입력 방식">
          <button role="tab" aria-selected={plan.method === 'area'} onClick={() => setPlan({ ...plan, method: 'area' })}>연면적 직접</button>
          <button role="tab" aria-selected={plan.method === 'massing'} onClick={() => setPlan({ ...plan, method: 'massing' })}>층수 × 동수</button>
        </div>
        <div className="field-grid">
          {plan.method === 'area' ? num('added_floor_area_m2', '추가 연면적', 'm²', 1000) : <>{num('floors', '층수', '층')}{num('building_count', '동수', '동')}{num('footprint_per_building', '동별 건축면적', 'm²', 50)}</>}
          {num('removed_floor_area_m2', '철거 연면적', 'm²', 1000)}
        </div>
        <p className="muted">계획 연면적 {formatMetric(plannedArea(plan), 'm²')}</p>
        <label className="area-target"><span>목표 감축률 (기준 연도 대비)</span><div><input type="range" min={0} max={100} step={1} value={target} onChange={(e) => setTarget(Number(e.target.value))} aria-label="목표 감축률 슬라이더" /><div className="with-unit"><input type="number" min={0} max={100} value={target} onChange={(e) => setTarget(Math.min(100, Math.max(0, Number(e.target.value))))} aria-label="목표 감축률" /><em>%</em></div></div></label>
        <div className="area-effort-basis"><span>기준 건물</span><div className="area-modes small" role="tablist" aria-label="감축 노력 기준 건물">
          {(['apartments', 'buildings'] as const).map((b) => <button key={b} role="tab" aria-selected={basis === b} onClick={() => setBasis(b)}>{EFFORT_BASIS_LABEL[b]}</button>)}
        </div><small className="muted">{basis === 'buildings' ? '상가·업무·학교 등 구역의 계측 건물 전체(건축HUB, 최근 12개월 완비 연도). 상업지역은 이 기준이 맞습니다.' : '공동주택 관리비 전력(같은 출처로 연도 비교). 주거지역 기본값.'}</small></div>
        <label className="field"><span>태양광 kW당 연 발전량 (선택)</span><div><input type="number" min={0} step={10} value={pvYield} placeholder="근거가 있을 때만 입력" onChange={(e) => setPvYield(e.target.value)} /><em>kWh/kW</em></div></label>
      </div>
      <div className="area-effort-result">
        {!effort ? <EmptyState title="목표를 넣으면 계산합니다" /> : !effort.available ? <EmptyState title="계산할 근거가 없습니다" description={effort.reason} /> : <>
          <div className="panel-title"><h3>필요한 노력</h3><div className="badge-row"><ProvenanceBadge kind="scenario" /><span className={`status-tag ${effort.baseline_mode === 'OBSERVED' ? 'good' : 'warn'}`}>기준 부하 {effort.baseline_mode === 'OBSERVED' ? '관측' : '추정'} · {effort.baseline_year}년{effort.basis ? ` · ${EFFORT_BASIS_LABEL[effort.basis]}` : ''}</span></div></div>
          {headline && <p className={`area-headline ${headline.tone}`} role="status">{headline.text}</p>}
          <EffortBars effort={effort} />
          <dl className="area-figures cols">
            <Figure label="필요 감축량" value={t(effort.required_reduction_kgco2eq)} unit="tCO₂eq/년" digits={1} />
            <Figure label="신축 부하 (추가 대책 없음)" value={effort.new_load_kwh} unit="kWh/년" />
            <div className={o?.new_only_efficiency_pct == null ? 'is-missing' : undefined}><dt>신축 건물만 개선할 때</dt><dd>{o?.new_only_efficiency_pct == null ? '신축 없음' : o.new_only_efficiency_pct > 100 ? `${formatMetric(o.new_only_efficiency_pct, '%', 1)} 필요 → 불가` : `${formatMetric(Math.max(0, o.new_only_efficiency_pct), '%', 1)} 절감`}<small>{o?.new_building_intensity_target != null ? `신축 원단위 ${o.new_building_intensity_target} kWh/m²·년 이하 (현재 ${formatMetric(effort.intensity_kwh_per_m2, '', 2)})` : '신축 원단위를 0 아래로 낮출 수 없음'}</small></dd></div>
            <Figure label="지역 전체 건물 효율 개선" value={o?.all_buildings_efficiency_pct != null ? Math.max(0, o.all_buildings_efficiency_pct) : null} unit="%" digits={1} note="기존 + 신축 전력 사용 절감률" />
            <Figure label="재생에너지로 상쇄할 전력" value={o?.offset_kwh_per_year} unit="kWh/년" />
            <Figure label="태양광 설비 용량" value={o?.pv_capacity_kw} unit="kW" digits={1} note={o?.pv_capacity_kw == null ? '발전량 가정 입력 시 계산' : '입력한 발전량 가정 기준'} />
          </dl>
          <EffortCurve effort={effort} />
          <div className="assumption-note"><strong>계산 가정 · {effort.scope}</strong><ul>{(effort.assumptions ?? []).map((a) => <li key={a}>{a}</li>)}</ul></div>
        </>}
      </div>
    </div>
  </section>;
}

function ReportPanel({ request, label }: { request: () => Record<string, unknown>; label: string }) {
  const recent = useApi<Array<{ id: string; created_at: string; title: string; mode: string }>>('/area-reports');
  const [useLocal, setUseLocal] = useState(false);
  const [title, setTitle] = useState('');
  const [report, setReport] = useState<AreaReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const create = async () => {
    const body = request();
    if (!body.area) { setError('먼저 구역을 분석하세요.'); return; }
    setBusy(true); setError(null);
    try {
      const next = await api<AreaReport>('/area-reports', { method: 'POST', body: JSON.stringify({ ...body, use_local_model: useLocal, title: title.trim() || null }) });
      setReport(next); void recent.reload();
    } catch (reason) { setError(reason instanceof Error ? reason.message : '보고서를 만들지 못했습니다.'); }
    finally { setBusy(false); }
  };
  const open = async (id: string) => { setError(null); try { setReport(await api<AreaReport>(`/area-reports/${id}`)); } catch (reason) { setError(reason instanceof Error ? reason.message : '보고서를 열지 못했습니다.'); } };
  const s = report?.summary;
  return <section className="panel area-report">
    <div className="area-report-form">
      <label className="area-select"><span>제목 (비우면 자동)</span><input type="text" maxLength={80} value={title} placeholder={`${label} 개발 영향·감축 검토`} onChange={(e) => setTitle(e.target.value)} /></label>
      <label className="area-check"><input type="checkbox" checked={useLocal} onChange={(e) => setUseLocal(e.target.checked)} /><span>로컬 AI로 요약 문장 쓰기<small>숫자·연도·증감 방향이 계산 결과와 하나라도 다르면 쓰지 않고 검증된 서식으로 바꿉니다.</small></span></label>
      <button className="button primary" onClick={() => void create()} disabled={busy}><FileText size={15} />{busy ? '작성 중…' : '현재 조건으로 보고서 작성'}</button>
    </div>
    {error && <p className="form-error" role="alert">{error}</p>}
    {report && s && <article className="area-report-body" data-testid="area-report">
      <header><h3>{report.title}</h3><div className="badge-row"><span className={`status-tag ${s.mode === 'TEMPLATE_FALLBACK' ? 'warn' : 'good'}`}>{REPORT_MODE_LABEL[s.mode]}</span><span className="muted">{formatDate(report.created_at)}</span></div></header>
      {s.reason && <p className="caveat">{s.reason}</p>}
      {s.paragraphs.map((p, i) => <p key={i}>{p}</p>)}
      {s.violations.length > 0 && <details><summary>불채택 사유 {s.violations.length}건</summary><ul>{s.violations.map((v) => <li key={v}>{v}</li>)}</ul>{s.rejected && <blockquote>{s.rejected}</blockquote>}</details>}
      {s.mode === 'LOCAL_SLM_NARRATIVE' && <details><summary>근거 문장 {report.facts.length}개</summary><ul>{report.facts.map((f) => <li key={f.id}>{f.text}</li>)}</ul></details>}
      <footer><small>검증: {s.validation} · 근거 SHA256 <code>{report.evidence_hash.slice(0, 16)}…</code></small><a className="button small" href={`/api/area-reports/${report.id}/markdown`}><Download size={14} />마크다운 내려받기</a></footer>
    </article>}
    {recent.data && recent.data.length > 0 && <div className="area-report-recent"><h4>최근 지역 보고서</h4><ul>{recent.data.slice(0, 6).map((r) => <li key={r.id}><button className="button ghost small" onClick={() => void open(r.id)}>{r.title}</button><small>{formatDate(r.created_at)} · {REPORT_MODE_LABEL[r.mode as AreaReport['summary']['mode']] ?? r.mode}</small></li>)}</ul></div>}
  </section>;
}
