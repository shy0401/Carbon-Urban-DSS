import * as maplibregl from 'maplibre-gl';
import workerUrl from 'maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url';
import { CheckCircle2, Clock3, Database, Globe2, Loader2, MapPinned, Play, Search, TriangleAlert } from 'lucide-react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { PageHeader } from '../components/PageHeader';
import { ErrorState, LoadingState } from '../components/Status';
import { setAnalysisScope, useAnalysisScope } from '../hooks/useAnalysisScope';
import { useApi } from '../hooks/useApi';
import { api } from '../lib/api';
import { formatDate, formatMetric } from '../lib/format';
import { classify, MISSING_FILL, rangeLabel, stepColor, type Classification } from '../lib/mapMetrics';
import { TOKENS } from '../theme/palette';
import type { NationalOverview, NationalRegionProps, RegionsResponse, RegionStep, RegionSummary } from '../types';

maplibregl.setWorkerUrl(workerUrl);

type MetricKey = 'density' | 'population' | 'households' | 'complexes';
const METRIC_OPTIONS: Array<{ key: MetricKey; label: string; unit: string; digits: number; ramp: 'seq' | 'load' }> = [
  { key: 'density', label: '인구밀도', unit: '명/km²', digits: 0, ramp: 'seq' },
  { key: 'population', label: '인구', unit: '명', digits: 0, ramp: 'seq' },
  { key: 'households', label: '가구', unit: '가구', digits: 0, ramp: 'seq' },
  { key: 'complexes', label: 'K-apt 공동주택 단지', unit: '곳', digits: 0, ramp: 'seq' },
];
const STATUS_LABEL: Record<string, string> = { READY: '준비 완료', PARTIAL: '일부 준비', PREPARING: '준비 중', NOT_PREPARED: '준비 전' };
const STEP_LABEL: Record<string, string> = { DONE: '완료', SKIPPED: '해당 없음', RUNNING: '수집 중', QUEUED: '대기', PENDING: '앞 단계 필요', WAITING: '한도 대기', BLOCKED: '키·승인 필요', FAILED: '실패' };
const NATIONAL_LAYERS: Array<{ key: string; label: string }> = [
  { key: 'admin_units', label: '법정 행정구역 코드' }, { key: 'sgis_national', label: 'SGIS 시군구·행정동 인구·가구·경계' },
  { key: 'kapt_national', label: 'K-apt 공동주택 단지 목록' }, { key: 'sgis_grid_1k', label: 'SGIS 1km 격자 통계' }, { key: 'sgis_grid', label: 'SGIS 공식 500m 격자 경계' },
];

export function statusTone(status: string | null | undefined) {
  if (status === 'READY' || status === 'DONE' || status === 'COLLECTED') return 'good';
  if (status === 'FAILED' || status === 'BLOCKED') return 'bad';
  if (status === 'PARTIAL' || status === 'WAITING') return 'warn';
  return 'neutral'; // 준비 전·대기·진행 중
}

/** Rows of the national table, sorted by the chosen metric (missing values last, never 0). */
export function regionRows(overview: NationalOverview | null, query: string, sido: string, metric: MetricKey) {
  const text = query.replace(/\s+/g, '');
  return (overview?.features ?? []).map((f) => f.properties)
    .filter((p) => (!sido || p.sido_name === sido) && (!text || p.name.replace(/\s+/g, '').includes(text)))
    .sort((a, b) => (b[metric] ?? -1) - (a[metric] ?? -1));
}

export function RegionsPage() {
  const { region: current } = useAnalysisScope();
  const navigate = useNavigate();
  const regions = useApi<RegionsResponse>('/regions');
  const overview = useApi<NationalOverview>('/regions/overview');
  const [metric, setMetric] = useState<MetricKey>('density');
  const [query, setQuery] = useState('');
  const [sido, setSido] = useState('');
  const [selected, setSelected] = useState<string | null>(null);
  const [detail, setDetail] = useState<RegionSummary | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const defaultRegion = regions.data?.default ?? '52110';
  const option = METRIC_OPTIONS.find((m) => m.key === metric) ?? METRIC_OPTIONS[0];
  const classification = useMemo<Classification>(() => classify((overview.data?.features ?? []).map((f) => f.properties[metric]), undefined, option.ramp), [overview.data, metric, option.ramp]);
  const rows = useMemo(() => regionRows(overview.data, query, sido, metric), [overview.data, query, sido, metric]);
  const sidoNames = useMemo(() => [...new Set((overview.data?.features ?? []).map((f) => f.properties.sido_name))].sort((a, b) => a.localeCompare(b, 'ko')), [overview.data]);
  const props = overview.data?.features.find((f) => f.properties.code === selected)?.properties ?? null;

  const loadDetail = useCallback(async (code: string) => {
    try { setDetail(await api<RegionSummary>(`/regions/${code}`)); } catch (e) { setMessage(e instanceof Error ? e.message : '지역 정보를 불러오지 못했습니다.'); }
  }, []);
  useEffect(() => { if (selected) void loadDetail(selected); else setDetail(null); }, [selected, loadDetail]);
  // While a region is being prepared, follow its steps.
  useEffect(() => {
    if (!selected || detail?.status !== 'PREPARING') return;
    const timer = window.setInterval(() => void loadDetail(selected), 5000);
    return () => window.clearInterval(timer);
  }, [selected, detail?.status, loadDetail]);
  const wasPreparing = useRef(false);
  useEffect(() => {
    if (wasPreparing.current && detail && detail.status !== 'PREPARING') { void regions.reload(); void overview.reload(); window.dispatchEvent(new Event('carbon-regions-change')); }
    wasPreparing.current = detail?.status === 'PREPARING';
  }, [detail?.status]); // eslint-disable-line react-hooks/exhaustive-deps

  const prepare = async (code: string) => {
    setBusy(true); setMessage(null);
    try { setDetail(await api<RegionSummary>(`/regions/${code}/prepare`, { method: 'POST', body: '{}' })); void loadDetail(code); }
    catch (e) { setMessage(e instanceof Error ? e.message : '지역 준비를 시작하지 못했습니다.'); }
    finally { setBusy(false); }
  };
  const collectNational = async () => {
    setBusy(true); setMessage(null);
    try { await api('/regions/national/collect', { method: 'POST', body: '{}' }); setMessage('전국 기초 자료 수집을 시작했습니다. 몇 분 뒤 새로고침하면 반영됩니다.'); }
    catch (e) { setMessage(e instanceof Error ? e.message : '수집을 시작하지 못했습니다.'); }
    finally { setBusy(false); }
  };
  const analyse = (code: string) => { setAnalysisScope({ region: code === defaultRegion ? null : code }); window.dispatchEvent(new Event('carbon-regions-change')); navigate('/map'); };

  if (regions.loading && !regions.data) return <div className="page"><LoadingState label="전국 지역 정보를 불러오는 중입니다" /></div>;
  if (regions.error || !regions.data) return <div className="page"><ErrorState message={regions.error} onRetry={regions.reload} /></div>;
  const national = regions.data.national;
  const ready = regions.data.regions.filter((r) => (r.grid_count ?? 0) > 0);

  return <div className="page regions-page">
    <PageHeader title="전국 지역" description="전국 시·군·구의 인구·주택 개요를 보고, 분석할 지역을 골라 그 지역 자료를 직접 수집해 준비합니다." action={<button type="button" className="button secondary" onClick={() => void collectNational()} disabled={busy}><Database size={15} aria-hidden="true" />전국 기초 자료 수집·갱신</button>} />
    {message && <p className="notice" role="status">{message}</p>}

    <section className="national-layers" aria-label="전국 기초 자료">
      <NationalFigure label="법정 행정구역" value={national.admin_units} unit="개" note={national.regions ? `분석 단위 시·군·구 ${national.regions}곳` : '아직 받지 않음'} />
      <NationalFigure label={`SGIS 인구·가구 ${national.sgis_year ?? ''}`.trim()} value={national.sgis_sigungu} unit="시군구" note={national.sgis_emd ? `행정동 ${national.sgis_emd.toLocaleString('ko-KR')}곳` : '행정동 미수집'} />
      <NationalFigure label="K-apt 공동주택 단지" value={national.complexes} unit="곳" note="전국 단지 목록 (좌표 포함)" />
      <NationalFigure label={`SGIS 1km 격자 ${national.grid1k_year ?? ''}`.trim()} value={national.grid1k_cells} unit="칸" note="인구·가구·주택·사업체 (잡음 포함)" />
      <NationalFigure label="SGIS 공식 500m 격자" value={national.grid500_official} unit="칸" note="경계·코드 (통계값은 신청 필요)" />
    </section>

    <div className="regions-layout">
      <section className="panel regions-map-panel">
        <div className="panel-title"><h3><Globe2 size={16} aria-hidden="true" /> 전국 시·군·구</h3>
          <label className="inline-select"><span>색</span><select value={metric} onChange={(e) => setMetric(e.target.value as MetricKey)} aria-label="지도 지표">{METRIC_OPTIONS.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}</select></label>
        </div>
        {overview.loading && !overview.data ? <LoadingState label="전국 경계를 불러오는 중입니다" /> : overview.error ? <ErrorState message={overview.error} onRetry={overview.reload} /> :
          <NationalMap overview={overview.data} metric={metric} classification={classification} selected={selected} onSelect={setSelected} />}
        <Legend classification={classification} unit={option.unit} digits={option.digits} source={overview.data?.meta.sources?.population ?? null} />
      </section>

      <aside className="panel region-detail" aria-live="polite">
        {!selected ? <div className="region-detail-empty"><MapPinned size={22} aria-hidden="true" /><p>지도나 표에서 시·군·구를 고르면 인구·주택 개요와 준비 상태가 여기에 나옵니다.</p>
          {ready.length > 0 && <><h4>분석할 수 있는 지역</h4><ul className="ready-list">{ready.map((r) => <li key={r.code}><button type="button" className="link-button" onClick={() => setSelected(r.code)}>{r.short_name}</button><span className={`status-tag ${statusTone(r.status)}`}>{STATUS_LABEL[r.status] ?? r.status}</span></li>)}</ul></>}
        </div> : <RegionDetail props={props} detail={detail} current={(current ?? defaultRegion) === selected} busy={busy} onPrepare={() => void prepare(selected)} onAnalyse={() => analyse(selected)} />}
      </aside>
    </div>

    <section className="panel">
      <div className="panel-title"><h3>시·군·구 목록 ({rows.length.toLocaleString('ko-KR')}곳)</h3>
        <div className="table-tools">
          <label className="search-field"><Search size={15} aria-hidden="true" /><input type="search" placeholder="이름으로 찾기 (예: 수원, 세종)" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="지역 이름 검색" /></label>
          <label className="inline-select"><span>시도</span><select value={sido} onChange={(e) => setSido(e.target.value)} aria-label="시도"><option value="">전체</option>{sidoNames.map((name) => <option key={name} value={name}>{name}</option>)}</select></label>
        </div>
      </div>
      <div className="table-wrap regions-table"><table>
        <thead><tr><th>지역</th><th>시도</th><th className="num">인구</th><th className="num">가구</th><th className="num">인구밀도 (명/km²)</th><th className="num">K-apt 단지</th><th>준비 상태</th></tr></thead>
        <tbody>{rows.map((p) => <tr key={p.code} className={p.code === selected ? 'selected' : undefined} onClick={() => setSelected(p.code)}>
          <td><button type="button" className="link-button" onClick={(e) => { e.stopPropagation(); setSelected(p.code); }}>{shortRegion(p.name)}</button>{p.districts.length > 0 && <small> ({p.districts.map((d) => d.name).join('·')})</small>}</td>
          <td>{p.sido_name}</td><td className="num">{formatMetric(p.population)}</td><td className="num">{formatMetric(p.households)}</td><td className="num">{formatMetric(p.density)}</td><td className="num">{p.complexes ? p.complexes.toLocaleString('ko-KR') : '-'}</td>
          <td><span className={`status-tag ${statusTone(p.study_status)}`}>{STATUS_LABEL[p.study_status] ?? p.study_status}</span></td>
        </tr>)}</tbody>
      </table></div>
      <p className="muted">인구·가구는 SGIS {overview.data?.meta.year ?? ''} 행정구역 통계(시군구 합계, 비공개 값은 합에서 빠짐)이고, 단지 수는 K-apt 의무관리 공동주택 목록입니다. 자료가 없는 칸은 0이 아니라 '자료 없음'입니다.</p>
    </section>

    <section className="panel national-sources">
      <div className="panel-title"><h3>전국 기초 자료 상태</h3></div>
      <ul>{NATIONAL_LAYERS.map(({ key, label }) => { const s = national.sources[key]; return <li key={key}><strong>{label}</strong><span className={`status-tag ${statusTone(s?.status)}`}>{s?.status ?? '미수집'}</span><small>{s?.quality ?? '아직 받지 않았습니다.'}{s?.collected_at ? ` · ${formatDate(s.collected_at)}` : ''}</small></li>; })}</ul>
      <p className="muted">전국 기초 자료는 요청 수가 적은 층(행정구역 코드, SGIS 시군구·행정동, K-apt 단지 목록, SGIS 500m 격자 경계)만 전국으로 받습니다. 호출 한도가 있는 층(건축HUB 에너지·건축물대장, K-apt 월별 에너지, VWorld 건물·용도지역)은 지역을 준비할 때 그 지역만 받습니다.</p>
    </section>
  </div>;
}

function shortRegion(name: string) { const parts = name.split(/\s+/); return parts.length > 1 ? parts.slice(1).join(' ') : name; }

function NationalFigure({ label, value, unit, note }: { label: string; value: number; unit: string; note: string }) {
  return <div className="national-figure"><span>{label}</span><strong>{value ? value.toLocaleString('ko-KR') : '-'}<small>{value ? unit : '미수집'}</small></strong><small>{note}</small></div>;
}

function Legend({ classification, unit, digits, source }: { classification: Classification; unit: string; digits: number; source: string | null }) {
  return <div className="map-legend-inline">
    <span className="legend-unit">{unit}</span>
    {classification.classes.map((c, i) => <span key={i} className="legend-item"><i style={{ background: c.color }} aria-hidden="true" />{rangeLabel(c, digits, i === classification.classes.length - 1)}</span>)}
    {classification.missing > 0 && <span className="legend-item"><i style={{ background: MISSING_FILL }} aria-hidden="true" />자료 없음 {classification.missing}곳</span>}
    {source && <small>{source}</small>}
  </div>;
}

function RegionDetail({ props, detail, current, busy, onPrepare, onAnalyse }: { props: NationalRegionProps | null; detail: RegionSummary | null; current: boolean; busy: boolean; onPrepare: () => void; onAnalyse: () => void }) {
  if (!detail) return <LoadingState label="지역 정보를 불러오는 중입니다" />;
  const steps: RegionStep[] = detail.steps ?? [];
  const hasGrid = (detail.grid_count ?? 0) > 0;
  const preparing = detail.status === 'PREPARING';
  return <div className="region-detail-body">
    <div className="region-detail-head"><div><h3>{detail.short_name ?? detail.name}</h3><small>{detail.sido_name}{detail.districts?.length ? ` · ${detail.districts.map((d) => d.name).join('·')}` : ''}</small></div>
      <span className={`status-tag ${statusTone(detail.status)}`}>{STATUS_LABEL[detail.status] ?? detail.status}</span></div>
    {props && <dl className="region-facts">
      <div><dt>인구</dt><dd>{formatMetric(props.population, '명')}</dd></div><div><dt>가구</dt><dd>{formatMetric(props.households, '가구')}</dd></div>
      <div><dt>면적</dt><dd>{formatMetric(props.area_km2, 'km²', 1)}</dd></div><div><dt>인구밀도</dt><dd>{formatMetric(props.density, '명/km²')}</dd></div>
      <div><dt>K-apt 단지</dt><dd>{props.complexes ? `${props.complexes.toLocaleString('ko-KR')}곳` : '-'}</dd></div><div><dt>분석 격자</dt><dd>{hasGrid ? `${(detail.grid_count ?? 0).toLocaleString('ko-KR')}개` : '없음'}</dd></div>
    </dl>}
    <div className="region-actions">
      {hasGrid && <button type="button" className="button primary" onClick={onAnalyse}><MapPinned size={15} aria-hidden="true" />{current ? '이 지역 지도 보기' : '이 지역 분석하기'}</button>}
      <button type="button" className={`button ${hasGrid ? 'secondary' : 'primary'}`} onClick={onPrepare} disabled={busy || preparing}>{preparing ? <><Loader2 size={15} className="spin" aria-hidden="true" />준비 중…</> : <><Play size={15} aria-hidden="true" />{detail.status === 'NOT_PREPARED' ? '이 지역 준비 (자료 수집)' : '남은 단계 이어서 수집'}</>}</button>
    </div>
    {detail.message && <p className="muted">{detail.message}</p>}
    <ol className="step-list">{steps.map((step) => <li key={step.id} className={`step ${step.status ? step.status.toLowerCase() : 'todo'}`}>
      <StepIcon status={step.status} /><div><strong>{step.label}</strong><small>{step.status ? STEP_LABEL[step.status] ?? step.status : '아직 안 함'}{step.message ? ` · ${step.message}` : ''}{step.resume_at ? ` · 재개 ${formatDate(step.resume_at)}` : ''}</small></div>
    </li>)}</ol>
    <p className="muted">격자는 SGIS 공식 500m 격자로 만들고, 호출 한도가 있는 단계(건축HUB 에너지·K-apt 에너지)는 한도가 풀리는 다음 날 자동으로 이어서 받습니다. 받지 못한 층은 0으로 채우지 않고 '자료 없음'으로 둡니다.</p>
  </div>;
}

function StepIcon({ status }: { status: string | null }) {
  if (status === 'DONE' || status === 'SKIPPED') return <CheckCircle2 size={16} className="step-icon good" aria-hidden="true" />;
  if (status === 'RUNNING') return <Loader2 size={16} className="step-icon spin" aria-hidden="true" />;
  if (status === 'FAILED' || status === 'BLOCKED') return <TriangleAlert size={16} className="step-icon bad" aria-hidden="true" />;
  return <Clock3 size={16} className="step-icon" aria-hidden="true" />;
}

function NationalMap({ overview, metric, classification, selected, onSelect }: { overview: NationalOverview | null; metric: MetricKey; classification: Classification; selected: string | null; onSelect: (code: string) => void }) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [ready, setReady] = useState(false);
  const select = useRef(onSelect); select.current = onSelect;
  const withGeometry = useMemo<GeoJSON.FeatureCollection>(() => ({ type: 'FeatureCollection', features: (overview?.features ?? []).filter((f) => f.geometry) as GeoJSON.Feature[] }), [overview]);

  useEffect(() => {
    if (!container.current) return;
    const map = new maplibregl.Map({
      container: container.current, center: [127.8, 36.2], zoom: 5.6, attributionControl: false,
      style: { version: 8, sources: {}, layers: [{ id: 'background', type: 'background', paint: { 'background-color': TOKENS.canvas } }] },
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'bottom-right');
    map.addControl(new maplibregl.AttributionControl({ compact: true, customAttribution: '경계·인구 SGIS, 단지 K-apt' }), 'bottom-right');
    map.on('load', () => {
      map.addSource('regions', { type: 'geojson', data: { type: 'FeatureCollection', features: [] }, promoteId: 'code' });
      map.addLayer({ id: 'regions-fill', type: 'fill', source: 'regions', paint: { 'fill-color': MISSING_FILL, 'fill-opacity': 0.92 } });
      map.addLayer({ id: 'regions-line', type: 'line', source: 'regions', paint: { 'line-color': TOKENS.surface, 'line-width': 0.6 } });
      map.addLayer({ id: 'regions-study', type: 'line', source: 'regions', filter: ['in', ['get', 'study_status'], ['literal', ['READY', 'PARTIAL', 'PREPARING']]], paint: { 'line-color': TOKENS.primary, 'line-width': 2 } });
      map.addLayer({ id: 'regions-selected', type: 'line', source: 'regions', filter: ['==', ['get', 'code'], ''], paint: { 'line-color': TOKENS['select-line'], 'line-width': 2.5 } });
      const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 8, maxWidth: '240px' });
      map.on('mousemove', 'regions-fill', (e) => {
        const p = e.features?.[0]?.properties; if (!p) return;
        map.getCanvas().style.cursor = 'pointer';
        const pop = typeof p.population === 'number' ? `인구 ${Number(p.population).toLocaleString('ko-KR')}명` : '인구 자료 없음';
        popup.setLngLat(e.lngLat).setHTML(`<strong>${escapeHtml(String(p.name ?? ''))}</strong><br>${pop}`).addTo(map);
      });
      map.on('mouseleave', 'regions-fill', () => { map.getCanvas().style.cursor = ''; popup.remove(); });
      map.on('click', 'regions-fill', (e) => { const code = e.features?.[0]?.properties?.code; if (code) select.current(String(code)); });
      setReady(true);
    });
    mapRef.current = map;
    return () => { map.remove(); mapRef.current = null; setReady(false); };
  }, []);

  useEffect(() => {
    const map = mapRef.current; if (!map || !ready) return;
    (map.getSource('regions') as maplibregl.GeoJSONSource | undefined)?.setData(withGeometry);
  }, [withGeometry, ready]);
  useEffect(() => {
    const map = mapRef.current; if (!map || !ready) return;
    map.setPaintProperty('regions-fill', 'fill-color', stepColor(metric, classification) as unknown as maplibregl.ExpressionSpecification);
  }, [metric, classification, ready]);
  useEffect(() => {
    const map = mapRef.current; if (!map || !ready) return;
    map.setFilter('regions-selected', ['==', ['get', 'code'], selected ?? '']);
  }, [selected, ready]);

  return <div className="national-map-wrap">
    <div ref={container} className="national-map" aria-label="전국 시·군·구 지도" />
    {withGeometry.features.length === 0 && <div className="map-empty-note">전국 경계가 아직 없습니다. '전국 기초 자료 수집·갱신'으로 SGIS 시군구 경계를 받으면 지도가 채워집니다.</div>}
  </div>;
}

function escapeHtml(value: string) { return value.replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c] ?? c); }
