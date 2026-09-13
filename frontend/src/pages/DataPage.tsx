import { AlertTriangle, CalendarDays, CheckCircle2, ChevronRight, CloudDownload, Database, ExternalLink, FileUp, RefreshCw, X } from 'lucide-react';
import { FormEvent, useCallback, useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { PageHeader } from '../components/PageHeader';
import { QualityBadge } from '../components/QualityBadge';
import { EmptyState, ErrorState, LoadingState } from '../components/Status';
import { useAnalysisScope } from '../hooks/useAnalysisScope';
import { api } from '../lib/api';
import { asRows, formatDate, formatMetric, qualityTone } from '../lib/format';
import type { CollectionJob, DataSource, SourceDetail } from '../types';

type ListResponse<T> = T[] | { items?: T[]; data?: T[]; jobs?: T[]; sources?: T[] };

export function DataPage() {
  const navigate = useNavigate();
  const {year}=useAnalysisScope();
  const [sources, setSources] = useState<DataSource[]>([]);
  const [jobs, setJobs] = useState<CollectionJob[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | number | null>(null);
  const [form, setForm] = useState({ datasets: ['energy', 'weather'], start_month: '2025-01', end_month: '2025-12' });
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
      const [sourceResponse, jobResponse] = await Promise.all([api<ListResponse<DataSource>>(`/sources?year=${year}`, {signal: request.signal}), api<ListResponse<CollectionJob>>('/collections', {signal: request.signal})]);
      if (request.signal.aborted) return;
      setSources(listFrom(sourceResponse, 'sources'));
      setJobs(listFrom(jobResponse, 'jobs'));
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
    <div className="data-layout">
      <form className="panel collection-form" onSubmit={submit}>
        <div className="panel-title"><div><span>NEW COLLECTION</span><h3>데이터 수집 요청</h3></div><CloudDownload size={20} /></div>
        <fieldset><legend>데이터셋</legend>{[['energy', '에너지'], ['weather', '기상']].map(([value, label]) => <label className="dataset-check" key={value}><input type="checkbox" checked={form.datasets.includes(value)} onChange={(event) => setForm((old) => ({ ...old, datasets: event.target.checked ? [...old.datasets, value] : old.datasets.filter((item) => item !== value) }))} /><span><CheckCircle2 size={17} /><strong>{label}</strong><small>{value === 'energy' ? '공식 건축물 에너지 관측' : '기상 관측 및 대체 자료'}</small></span></label>)}</fieldset>
        <div className="month-fields"><label><span>시작 월</span><input type="month" value={form.start_month} onChange={(event) => setForm((old) => ({ ...old, start_month: event.target.value }))} /></label><label><span>종료 월</span><input type="month" value={form.end_month} onChange={(event) => setForm((old) => ({ ...old, end_month: event.target.value }))} /></label></div>
        {formError && <p className="form-error"><AlertTriangle size={15} />{formError}</p>}
        <button className="button primary full" disabled={submitting}><CloudDownload size={16} />{submitting ? '요청 중…' : '수집 작업 시작'}</button>
        <p className="form-caption">수집은 백그라운드에서 실행되며 아래 작업 이력이 자동 갱신됩니다.</p>
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
