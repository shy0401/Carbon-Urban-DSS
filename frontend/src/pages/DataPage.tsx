import { AlertTriangle, ArrowRight, BrainCircuit, Calculator, CalendarDays, CheckCircle2, ChevronRight, CloudDownload, Database, ExternalLink, FileArchive, FileText, FileUp, KeyRound, Map, RefreshCw, ShieldCheck, X } from 'lucide-react';
import { FormEvent, useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { PageHeader } from '../components/PageHeader';
import { QualityBadge } from '../components/QualityBadge';
import { EmptyState, ErrorState, LoadingState } from '../components/Status';
import { useAnalysisScope } from '../hooks/useAnalysisScope';
import { api } from '../lib/api';
import { asRows, formatDate, formatMetric, qualityTone } from '../lib/format';
import type { CollectionJob, DataSource, LocalEngineStatus, ReadinessData, ReadinessSource, SourceDetail } from '../types';

type ListResponse<T> = T[] | { items?: T[]; data?: T[]; jobs?: T[]; sources?: T[] };
const collectionDatasets = [
  ['kapt_energy', 'K-apt 에너지', '단지별 월 사용량 · 먼저 1단지 1개월 검증'],
  ['kma_asos', 'KMA ASOS', '전주 146 공식 일자료 · 완전한 월만 우선'],
  ['sgis', 'SGIS 인구·가구', '행정구역 통계 · 500m 격자와 분리'],
  ['vworld_zoning', 'VWorld 용도지역', '공식 LT_C_UQ111 레이어'],
  ['vworld_cadastral', 'VWorld 연속지적', '공식 LP_PA_CBND_BUBUN 레이어'],
  ['energy', '건축HUB 에너지', '지번별 전력·가스 사용량'],
  ['weather', 'ERA5-Land 기상', '재분석 대체 자료'],
] as const;

export function DataPage() {
  const navigate = useNavigate();
  const {year}=useAnalysisScope();
  const [sources, setSources] = useState<DataSource[]>([]);
  const [jobs, setJobs] = useState<CollectionJob[]>([]);
  const [readiness, setReadiness] = useState<ReadinessData | null>(null);
  const [engine, setEngine] = useState<LocalEngineStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | number | null>(null);
  const [form, setForm] = useState({ datasets: ['kapt_energy'], start_month: '2025-01', end_month: '2025-12', scope: 'smoke' });
  useEffect(()=>setForm(old=>({...old,start_month:`${year}-01`,end_month:`${year}-12`})),[year]);
  const [submitting, setSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  const requestRef = useRef<AbortController | null>(null);
  const load = useCallback(async (quiet = false) => {
    requestRef.current?.abort();
    const request = new AbortController();
    requestRef.current = request;
    if (!quiet) setLoading(true);
    try {
      const [sourceResponse, jobResponse, readinessResponse, engineResponse] = await Promise.all([api<ListResponse<DataSource>>(`/sources?year=${year}`, {signal: request.signal}), api<ListResponse<CollectionJob>>('/collections', {signal: request.signal}), api<ReadinessData>('/readiness', {signal: request.signal}), api<LocalEngineStatus>('/reports/engine', {signal: request.signal})]);
      if (request.signal.aborted) return;
      setSources(listFrom(sourceResponse, 'sources'));
      setJobs(listFrom(jobResponse, 'jobs'));
      setReadiness(readinessResponse);
      setEngine(engineResponse);
      setError(null);
    } catch (reason) { if (!request.signal.aborted && !quiet) setError(reason instanceof Error ? reason.message : '데이터를 불러오지 못했습니다.'); }
    finally { if (!request.signal.aborted && !quiet) setLoading(false); }
  }, [year]);

  useEffect(() => { void load(); return () => requestRef.current?.abort(); }, [load]);
  useEffect(() => {
    const active = jobs.some((job) => ['PENDING', 'QUEUED', 'RUNNING', 'STARTED'].includes(job.status.toUpperCase()));
    if (!active) return;
    const timer = window.setInterval(() => void load(true), 3000);
    return () => window.clearInterval(timer);
  }, [jobs, load]);

  const submit = async (event: FormEvent) => {
    event.preventDefault(); setFormError(null);
    if (!form.datasets.length) { setFormError('하나 이상의 데이터셋을 선택하세요.'); return; }
    if (form.start_month > form.end_month) { setFormError('시작 월은 종료 월보다 앞서야 합니다.'); return; }
    setSubmitting(true);
    try {
      await api('/collections', { method: 'POST', body: JSON.stringify(form) });
      await load(true);
    } catch (reason) { setFormError(reason instanceof Error ? reason.message : '수집 요청에 실패했습니다.'); }
    finally { setSubmitting(false); }
  };

  if (loading) return <div className="page"><LoadingState label="출처와 수집 이력을 불러오는 중입니다" /></div>;
  if (error) return <div className="page"><ErrorState message={error} onRetry={() => void load()} /></div>;
  const sourceSummary = summarizeSources(sources);
  return <div className="page">
    <PageHeader eyebrow="DATA OPERATIONS" title="수집 데이터" description="공식·대체 출처의 수집 범위와 원본에서 정규화까지의 이력을 확인합니다." action={<button className="button secondary" onClick={() => void load()}><RefreshCw size={15} />새로고침</button>} />
    <p className="panel-description"><a href="https://github.com/shy0401/Carbon-Urban-DSS/blob/main/docs/DATA_SETUP_GUIDE.md" target="_blank" rel="noopener noreferrer">자료별 인증키 신청 · 다운로드 · 필드 매핑 안내</a></p>
    <section className="data-summary">{sourceSummary.map(([label, value, tone]) => <article className={tone} key={label}><span>{label}</span><strong>{value}</strong></article>)}<article><span>마지막 수집</span><strong>{latestCollection(sources)}</strong></article></section>
    {readiness && <ReadinessOverview data={readiness} />}
    {engine && <LocalAiFlow engine={engine} />}
    <div className="data-layout">
      <form className="panel collection-form" onSubmit={submit}>
        <div className="panel-title"><div><span>NEW COLLECTION</span><h3>데이터 수집 요청</h3></div><CloudDownload size={20} /></div>
        <fieldset><legend>데이터셋</legend>{collectionDatasets.map(([value, label, description]) => <label className="dataset-check" key={value}><input type="checkbox" checked={form.datasets.includes(value)} onChange={(event) => setForm((old) => ({ ...old, datasets: event.target.checked ? [...old.datasets, value] : old.datasets.filter((item) => item !== value) }))} /><span><CheckCircle2 size={17} /><strong>{label}</strong><small>{description}</small></span></label>)}</fieldset>
        <label><span>수집 범위</span><select aria-label="수집 범위" value={form.scope} onChange={(event) => setForm((old) => ({ ...old, scope: event.target.value }))}><option value="smoke">SMOKE · 최소 1건 검증</option><option value="limited">LIMITED · 제한 범위</option><option value="full">FULL · 전체 범위</option></select></label>
        <div className="month-fields"><label><span>시작 월</span><input type="month" value={form.start_month} onChange={(event) => setForm((old) => ({ ...old, start_month: event.target.value }))} /></label><label><span>종료 월</span><input type="month" value={form.end_month} onChange={(event) => setForm((old) => ({ ...old, end_month: event.target.value }))} /></label></div>
        {formError && <p className="form-error"><AlertTriangle size={15} />{formError}</p>}
        <button className="button primary full" disabled={submitting}><CloudDownload size={16} />{submitting ? '요청 중…' : '수집 작업 시작'}</button>
        <p className="form-caption">수집은 백그라운드에서 실행됩니다. K-apt와 VWorld의 FULL은 같은 연도·출처의 SMOKE 성공 후에만 시작됩니다.</p>
      </form>
      <section className="panel jobs-panel"><div className="panel-title"><div><span>COLLECTION JOBS</span><h3>작업 이력</h3></div><CalendarDays size={20} /></div>
        {jobs.length ? <div className="job-list">{jobs.map((job) => <article key={job.id}><div className={`job-state ${qualityTone(job.status)}`}><span>{statusLabel(job.status)}</span><small>#{job.id}</small></div><div className="job-body"><strong>{job.dataset ?? job.datasets?.join(', ') ?? '데이터 수집'}</strong><small>{formatDate(job.updated_at ?? job.created_at)}</small>{job.message && <p>{job.message}</p>}{job.error && <p className="error-text">{job.error}</p>}{typeof job.progress === 'number' && <div className="progress"><span style={{ width: `${Math.max(0, Math.min(100, job.progress))}%` }} /></div>}</div></article>)}</div> : <EmptyState title="수집 작업 이력이 없습니다" />}
      </section>
    </div>
    <section className="panel source-catalog"><div className="panel-title"><div><span>DATA CATALOG</span><h3>연결된 데이터 출처</h3></div><Database size={20} /></div>
      {sources.length ? <div className="source-cards">{sources.map((source) => <button className="source-card" key={source.id} onClick={() => navigate(`/data/sources/${source.id}`)}><div className="source-card-head"><span>{source.category}</span><QualityBadge value={source.quality} /></div><h4>{source.name}</h4><p>{source.organization ?? '기관 정보 없음'}</p><dl><div><dt>수집 상태</dt><dd>{statusLabel(source.status)}</dd></div><div><dt>정규화</dt><dd>{formatMetric(source.normalized_row_count, '행')}</dd></div><div><dt>기준 기간</dt><dd>{source.reference_period ?? '기록 없음'}</dd></div><div><dt>종합 품질</dt><dd>{score(source.quality_scores?.overall)}</dd></div></dl>{source.limitation && <small className="limitation"><AlertTriangle size={13} />{source.limitation}</small>}<span className="card-action">상세 보기 <ChevronRight size={15} /></span></button>)}</div> : <EmptyState title="연결된 데이터 출처가 없습니다" description="위 수집 양식으로 실제 자료 수집을 요청해 주세요." />}
    </section>
    <ManualUpload onImported={() => void load(true)} />
    {selected !== null && <SourceModal sourceId={selected} onClose={() => setSelected(null)} />}
  </div>;
}

function ReadinessOverview({ data }: { data: ReadinessData }) {
  const summary = [
    ['수집·연결 완료', (data.summary.states.COLLECTED ?? 0) + (data.summary.states.PARTIAL ?? 0), 'good'],
    ['지금 자동 실행 가능', data.summary.collectable_now, 'good'],
    ['키·승인·오류 확인', (data.summary.states.CREDENTIAL_REQUIRED ?? 0) + (data.summary.states.APPROVAL_OR_FIX_REQUIRED ?? 0), 'warn'],
    ['공식 파일 직접 필요', data.summary.states.MANUAL_REQUIRED ?? 0, 'manual'],
  ] as const;
  return <>
    <section className="panel readiness-panel">
      <div className="panel-title"><div><span>DATA READINESS</span><h3>현재 수집 가능성과 차단 요인</h3></div><ShieldCheck size={21} /></div>
      <div className="readiness-summary">{summary.map(([label, value, tone]) => <article className={tone} key={label}><strong>{value}</strong><span>{label}</span></article>)}</div>
      <div className="truth-rules">{data.truth_rules.map((rule) => <span key={rule}><CheckCircle2 size={14} />{rule}</span>)}</div>
    </section>
    <section className="panel pipeline-panel">
      <div className="panel-title"><div><span>DATA LINEAGE</span><h3>데이터가 의사결정으로 연결되는 과정</h3></div><Database size={21} /></div>
      <div className="pipeline-flow">{data.pipeline.map((step, index) => <div className="pipeline-segment" key={step.id}><article><span>{String(index + 1).padStart(2, '0')}</span><strong>{step.label}</strong><b>{formatMetric(step.value, step.id === 'spatial' || step.id === 'analyze' ? '행' : '건')}</b><small>{step.detail}</small></article>{index < data.pipeline.length - 1 && <ArrowRight aria-hidden="true" size={18} />}</div>)}</div>
    </section>
    <section className="panel readiness-catalog">
      <div className="panel-title"><div><span>SOURCE TO USE</span><h3>수집 정보와 실제 활용처</h3></div><Map size={21} /></div>
      <div className="readiness-source-grid">{data.sources.map((source) => <ReadinessCard key={source.id} source={source} />)}</div>
    </section>
  </>;
}

function ReadinessCard({ source }: { source: ReadinessSource }) {
  const tone = readinessTone(source.state);
  return <article className={`readiness-source ${tone}`}>
    <header><div><span>{acquisitionLabel(source.acquisition)}</span><h4>{source.name}</h4><small>{source.organization ?? '프로젝트 내부 산출'}</small></div><b>{readinessLabel(source.state)}</b></header>
    <div className="row-counts"><span>원본 <strong>{formatMetric(source.raw_rows, '건')}</strong></span><ArrowRight size={14} /><span>정규화 <strong>{formatMetric(source.normalized_rows, '행')}</strong></span></div>
    {source.credentials.length > 0 && <div className="credential-list">{source.credentials.map((credential) => <span className={credential.configured ? 'configured' : 'missing'} key={credential.name}><KeyRound size={12} />{credential.name}<b>{credential.configured ? '설정됨' : '필요'}</b></span>)}</div>}
    <div className="source-use-flow"><div><small>수집 정보</small>{source.products.length ? source.products.map((item) => <span key={item}>{item}</span>) : <span>카탈로그 정보</span>}</div><ArrowRight size={17} /><div><small>활용 화면·분석</small>{source.uses.length ? source.uses.map((item) => <span key={item}>{item}</span>) : <span>출처 현황 표시</span>}</div></div>
    {source.scopes.smoke && <p className="scope-line"><strong>첫 검증</strong>{source.scopes.smoke}</p>}
    {source.blocker && <p className="source-blocker"><AlertTriangle size={13} />{source.blocker}</p>}
  </article>;
}

function LocalAiFlow({ engine }: { engine: LocalEngineStatus }) {
  const steps = [
    { icon: FileArchive, label: '검증된 DB·원본', detail: '출처와 계산 결과 고정' },
    { icon: Calculator, label: '결정론적 계산', detail: '탄소·시나리오 수치 생성' },
    { icon: BrainCircuit, label: '로컬 Ollama', detail: '허용된 근거 ID만 선택' },
    { icon: FileText, label: '한국어 보고서', detail: '근거 해시와 출처 보존' },
  ];
  return <section className="panel ai-flow-panel">
    <div className="panel-title"><div><span>LOCAL AI</span><h3>로컬 LLM 운영 구조</h3></div><span className={`badge ${engine.status === 'READY' ? 'good' : 'warn'}`}>{engine.status === 'READY' ? '사용 가능' : '설치·연결 필요'}</span></div>
    <div className="ai-flow">{steps.map(({ icon: Icon, label, detail }, index) => <div className="ai-flow-step" key={label}><article><Icon size={20} /><strong>{label}</strong><small>{detail}</small></article>{index < steps.length - 1 && <ArrowRight size={18} />}</div>)}</div>
    <div className="ai-contract"><span><b>모델</b>{engine.model ?? '설치 전'} · {engine.provider}</span><span><b>허용</b>{engine.allowed_tasks.join(' · ')}</span><span><b>금지</b>{engine.prohibited_tasks}</span><span><b>처리 위치</b>{engine.privacy}</span></div>
  </section>;
}

function SourceModal({ sourceId, onClose }: { sourceId: string | number; onClose: () => void }) {
  const [detail, setDetail] = useState<SourceDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<'raw' | 'normalized' | 'history'>('raw');
  useEffect(() => { api<SourceDetail>(`/sources/${encodeURIComponent(String(sourceId))}`).then(setDetail).catch((reason) => setError(reason instanceof Error ? reason.message : '상세 정보를 불러오지 못했습니다.')); }, [sourceId]);
  return <div className="modal-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}><section className="modal" role="dialog" aria-modal="true" aria-label="데이터 출처 상세">
    <header><div><span className="eyebrow">SOURCE DETAIL</span><h2>{detail?.source.name ?? '출처 상세'}</h2><p>{detail?.source.organization ?? '출처 정보를 불러오는 중입니다.'}</p></div><button aria-label="닫기" onClick={onClose}><X /></button></header>
    {!detail && !error && <LoadingState />}{error && <ErrorState message={error} onRetry={() => window.location.reload()} />}
    {detail && <><div className="source-meta"><QualityBadge value={detail.source.quality} /><span>{detail.source.reference_period ?? '기간 기록 없음'}</span><span>{detail.source.geographic_coverage ?? '범위 기록 없음'}</span>{detail.source.source_url && <a href={detail.source.source_url} target="_blank" rel="noreferrer">원문 <ExternalLink size={14} /></a>}</div>
      <div className="tabs" role="tablist"><button role="tab" aria-selected={tab === 'raw'} onClick={() => setTab('raw')}>원본 미리보기</button><button role="tab" aria-selected={tab === 'normalized'} onClick={() => setTab('normalized')}>정규화 미리보기</button><button role="tab" aria-selected={tab === 'history'} onClick={() => setTab('history')}>수집 이력</button></div>
      <div className="modal-content">{tab === 'history' ? <History detail={detail} /> : <PreviewTable value={tab === 'raw' ? detail.raw_preview : detail.normalized_preview} />}</div>
      {detail.source.limitation && <div className="modal-limitation"><AlertTriangle size={17} /><div><strong>자료 제한사항</strong><p>{detail.source.limitation}</p></div></div>}</>}
  </section></div>;
}

function PreviewTable({ value }: { value: unknown }) {
  const rows = asRows(value);
  if (!rows.length) return <EmptyState title="미리보기 자료가 없습니다" />;
  const columns = Array.from(new Set(rows.flatMap((row) => Object.keys(row)))).slice(0, 10);
  return <div className="table-wrap"><table><thead><tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{rows.slice(0, 20).map((row, index) => <tr key={index}>{columns.map((column) => <td key={column}>{renderCell(row[column])}</td>)}</tr>)}</tbody></table></div>;
}

function History({ detail }: { detail: SourceDetail }) {
  return <div className="history-list">{detail.jobs?.length ? detail.jobs.map((job) => <article key={job.id}><span className={`history-icon ${qualityTone(job.status)}`}><CheckCircle2 size={17} /></span><div><strong>{statusLabel(job.status)}</strong><p>{job.message ?? job.error ?? '추가 메시지 없음'}</p><small>{formatDate(job.updated_at ?? job.created_at)}</small></div></article>) : <EmptyState title="수집 이력이 없습니다" />}{asRows(detail.errors).map((item, index) => <article key={`error-${index}`}><span className="history-icon bad"><AlertTriangle size={17} /></span><div><strong>수집 오류</strong><p>{renderCell(item.message ?? item.error ?? item)}</p></div></article>)}</div>;
}

function listFrom<T>(response: ListResponse<T>, key: string): T[] { if (Array.isArray(response)) return response; const record = response as Record<string, unknown>; const value = record[key] ?? record.items ?? record.data; return Array.isArray(value) ? value as T[] : []; }
function renderCell(value: unknown): string { if (value === null || value === undefined) return '자료 없음'; if (typeof value === 'object') return JSON.stringify(value); return String(value); }
function statusLabel(status: string | null | undefined) { const value = status?.toUpperCase(); return ({ NOT_COLLECTED: '미수집', COLLECTED: '수집 완료', PARTIAL: '부분 수집', NEEDS_API_KEY: '인증키 필요', NEEDS_API_APPROVAL: '활용 승인 필요', MANUAL_DOWNLOAD_REQUIRED: '수동 자료 필요', COMPLETED: '완료', SUCCESS: '완료', RUNNING: '수집 중', STARTED: '수집 중', PENDING: '대기', QUEUED: '대기', FAILED: '실패', ERROR: '오류', ACTIVE: '활성' } as Record<string, string>)[value ?? ''] ?? status ?? '상태 없음'; }
function readinessLabel(state: string) { return ({ COLLECTED: '수집 완료', PARTIAL: '부분 확보', AVAILABLE: '수집 가능', CREDENTIAL_REQUIRED: '키 설정 필요', APPROVAL_OR_FIX_REQUIRED: '승인·오류 확인', MANUAL_REQUIRED: '직접 수집 필요', REPLACED: '대체 출처 사용', NOT_COLLECTED: '미수집' } as Record<string, string>)[state] ?? state; }
function readinessTone(state: string) { if (state === 'COLLECTED' || state === 'AVAILABLE') return 'ready'; if (state === 'PARTIAL') return 'partial'; if (state === 'MANUAL_REQUIRED') return 'manual'; return 'blocked'; }
function acquisitionLabel(value: string) { return ({ API_KEY: '인증 API', MANUAL_DOWNLOAD: '공식 파일', OPEN_API: '공개 API', OPEN_FILE: '공개 파일', OPEN_WEB: '공개 웹', DERIVED: '프로젝트 파생', CATALOG: '카탈로그' } as Record<string, string>)[value] ?? value; }

interface UploadPreview { id: string; columns: string[]; rows: Array<Record<string, unknown>>; detected_crs?: string | null; encoding?: string | null; required_fields?: string[]; suggested_mapping?: Record<string, string>; warnings?: string[]; filename?: string; }

function ManualUpload({ onImported }: { onImported: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [datasetType, setDatasetType] = useState('building_register');
  const [preview, setPreview] = useState<UploadPreview | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [meta, setMeta] = useState({ provider: '', source_url: '', reference_period: '', source_crs: '' });
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const makePreview = async (event: FormEvent) => {
    event.preventDefault(); if (!file) { setMessage('업로드할 파일을 선택하세요.'); return; }
    setBusy(true); setMessage(null);
    const body = new FormData(); body.append('file', file); body.append('dataset_type', datasetType);
    try { const result = await api<UploadPreview>('/uploads/preview', { method: 'POST', body }); setPreview(result); setMapping(result.suggested_mapping ?? {}); setMeta((old) => ({ ...old, source_crs: result.detected_crs ?? old.source_crs })); }
    catch (reason) { setMessage(reason instanceof Error ? reason.message : '파일 분석에 실패했습니다.'); }
    finally { setBusy(false); }
  };
  const importFile = async () => {
    if (!preview) return;
    const missing = (preview.required_fields ?? []).filter((field) => !mapping[field]);
    if (missing.length) { setMessage(`필수 매핑을 선택하세요: ${missing.join(', ')}`); return; }
    if (!meta.provider || !meta.reference_period) { setMessage('제공기관과 기준기간을 입력하세요.'); return; }
    setBusy(true); setMessage(null);
    try { await api(`/uploads/${preview.id}/import`, { method: 'POST', body: JSON.stringify({ mapping, ...meta }) }); setMessage('가져오기 작업이 시작되었습니다.'); setPreview(null); setFile(null); onImported(); }
    catch (reason) { setMessage(reason instanceof Error ? reason.message : '가져오기에 실패했습니다.'); }
    finally { setBusy(false); }
  };
  return <section className="panel upload-panel"><div className="panel-title"><div><span>CONTROLLED IMPORT</span><h3>수동 파일 업로드</h3></div><FileUp size={20} /></div><p className="panel-description">자동 접근이 어려운 공식 CSV, XLSX, GeoJSON, SHP ZIP을 먼저 분석한 뒤 열 매핑을 확인합니다.</p>
    {!preview ? <form className="upload-start" onSubmit={makePreview}><select value={datasetType} onChange={(event) => setDatasetType(event.target.value)}><option value="building_register">건축물대장</option><option value="building_geometry">건물 공간정보</option><option value="zoning">용도지역</option><option value="population_grid">인구 통계격자</option><option value="energy">에너지</option></select><input type="file" accept=".csv,.xlsx,.geojson,.json,.zip" onChange={(event) => setFile(event.target.files?.[0] ?? null)} /><button className="button secondary" disabled={busy}><FileUp size={15} />{busy ? '분석 중…' : '파일 분석'}</button></form> : <div className="mapping-preview"><div className="detected-meta"><span>인코딩 <strong>{preview.encoding ?? '감지 안 됨'}</strong></span><span>좌표계 <strong>{preview.detected_crs ?? '감지 안 됨'}</strong></span><span>열 <strong>{preview.columns.length}개</strong></span></div>{preview.warnings?.map((warning) => <p className="form-error" key={warning}><AlertTriangle size={15} />{warning}</p>)}<div className="mapping-grid">{(preview.required_fields ?? Object.keys(preview.suggested_mapping ?? {})).map((field) => <label key={field}><span>{field}</span><select value={mapping[field] ?? ''} onChange={(event) => setMapping((old) => ({ ...old, [field]: event.target.value }))}><option value="">매핑 선택</option>{preview.columns.map((column) => <option key={column}>{column}</option>)}</select></label>)}</div><div className="mapping-grid metadata"><label><span>제공기관 *</span><input value={meta.provider} onChange={(event) => setMeta((old) => ({ ...old, provider: event.target.value }))} /></label><label><span>공식 URL</span><input value={meta.source_url} onChange={(event) => setMeta((old) => ({ ...old, source_url: event.target.value }))} /></label><label><span>기준기간 *</span><input placeholder="예: 2025" value={meta.reference_period} onChange={(event) => setMeta((old) => ({ ...old, reference_period: event.target.value }))} /></label><label><span>원본 좌표계</span><input placeholder="예: EPSG:5179" value={meta.source_crs} onChange={(event) => setMeta((old) => ({ ...old, source_crs: event.target.value }))} /></label></div><PreviewTable value={preview.rows} /><div className="form-actions"><button className="button ghost" onClick={() => setPreview(null)}>취소</button><button className="button primary" onClick={() => void importFile()} disabled={busy}>{busy ? '가져오는 중…' : '매핑 확인 및 가져오기'}</button></div></div>}
    {message && <p className="upload-message">{message}</p>}
  </section>;
}

function summarizeSources(sources: DataSource[]): Array<[string, number, string]> { const status = (s: DataSource) => s.status.toUpperCase(); return [['연결된 데이터 소스', sources.length, ''], ['정상 수집', sources.filter((s) => ['COLLECTED', 'COMPLETED', 'SUCCESS'].includes(status(s))).length, 'good'], ['부분 수집', sources.filter((s) => ['PARTIAL', 'FALLBACK'].includes(status(s)) || s.quality?.toUpperCase() === 'FALLBACK').length, 'warn'], ['추가 인증 필요', sources.filter((s) => ['NEEDS_API_KEY', 'NEEDS_API_APPROVAL', 'MANUAL_DOWNLOAD_REQUIRED'].includes(status(s))).length, 'warn'], ['오류', sources.filter((s) => ['ERROR', 'FAILED'].includes(status(s))).length, 'bad']]; }
function latestCollection(sources: DataSource[]) { const values = sources.map((source) => source.collected_at).filter(Boolean) as string[]; return values.length ? formatDate(values.sort().at(-1)) : '기록 없음'; }
function score(value: number | null | undefined) { return value === null || value === undefined ? '미산정' : `${Math.round(value * 100)}%`; }
