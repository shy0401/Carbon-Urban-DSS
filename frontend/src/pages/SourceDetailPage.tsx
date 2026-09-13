import { AlertTriangle, ArrowLeft, CheckCircle2, ExternalLink, FileKey, ShieldCheck } from 'lucide-react';
import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { PageHeader } from '../components/PageHeader';
import { QualityBadge } from '../components/QualityBadge';
import { QualityScores } from '../components/QualityScores';
import { EmptyState, ErrorState, LoadingState } from '../components/Status';
import { useApi } from '../hooks/useApi';
import { asRows, formatDate, formatMetric, qualityTone } from '../lib/format';
import type { SourceDetail } from '../types';

type DetailTab = 'info' | 'raw' | 'normalized' | 'history' | 'quality' | 'errors';

export function SourceDetailPage() {
  const { id } = useParams();
  const { data, loading, error, reload } = useApi<SourceDetail>(`/sources/${encodeURIComponent(id ?? '')}`);
  const [tab, setTab] = useState<DetailTab>('info');
  if (loading) return <div className="page"><LoadingState label="출처 상세를 불러오는 중입니다" /></div>;
  if (error || !data) return <div className="page"><ErrorState message={error} onRetry={reload} /></div>;
  const source = data.source;
  const tabs: Array<[DetailTab, string]> = [['info', '기본 정보'], ['raw', '원천 데이터'], ['normalized', '정제 데이터'], ['history', '수집 이력'], ['quality', '품질 검사'], ['errors', '오류 로그']];
  return <div className="page source-detail-page">
    <Link className="back-link" to="/data"><ArrowLeft size={15} />수집 데이터로 돌아가기</Link>
    <PageHeader eyebrow="DATA PROVENANCE" title={source.name} description={`${source.organization ?? '제공기관 미기록'} · ${source.reference_period ?? '기준기간 미기록'}`} action={<QualityBadge value={source.quality} />} />
    <div className="detail-tabs" role="tablist">{tabs.map(([key, label]) => <button key={key} role="tab" aria-selected={tab === key} onClick={() => setTab(key)}>{label}</button>)}</div>
    <section className="panel detail-body">
      {tab === 'info' && <div className="detail-info"><div><h3>출처 및 수집 정보</h3><dl className="detail-dl"><div><dt>제공기관</dt><dd>{source.organization ?? '기록 없음'}</dd></div><div><dt>데이터 유형</dt><dd>{source.source_type ?? '기록 없음'}</dd></div><div><dt>라이선스</dt><dd>{source.license ?? '확인 필요'}</dd></div><div><dt>지역 범위</dt><dd>{source.geographic_coverage ?? '기록 없음'}</dd></div><div><dt>수집 시각</dt><dd>{formatDate(source.collected_at)}</dd></div><div><dt>원본 / 정규화</dt><dd>{formatMetric(source.raw_row_count, '행')} / {formatMetric(source.normalized_row_count, '행')}</dd></div></dl>{source.source_url && <a className="source-url" href={source.source_url} target="_blank" rel="noreferrer">공식 출처 열기 <ExternalLink size={14} /></a>}</div><div><h3>스키마</h3><CodeBlock value={source.schema ?? data.fields ?? []} /></div></div>}
      {tab === 'raw' && <><AssetList assets={data.assets ?? []} /><Preview value={data.raw_preview} /></>}
      {tab === 'normalized' && <Preview value={data.normalized_preview} />}
      {tab === 'history' && <div className="history-list">{data.jobs?.length ? data.jobs.map((job) => <article key={job.id}><span className={`history-icon ${qualityTone(job.status)}`}><CheckCircle2 size={17} /></span><div><strong>{job.status}</strong><p>{job.message ?? job.error ?? '추가 메시지 없음'}</p><small>{formatDate(job.updated_at ?? job.created_at)}</small></div></article>) : <EmptyState title="수집 이력이 없습니다" />}</div>}
      {tab === 'quality' && <div className="quality-detail"><div><h3>구성 점수</h3><p>종합 점수만으로 품질을 판단하지 않고 각 구성 요소를 함께 확인합니다.</p><QualityScores scores={source.quality_scores} /></div><div className="quality-context"><ShieldCheck size={28} /><h3>품질 근거</h3><CodeBlock value={data.coverage} />{source.limitation && <div className="modal-limitation"><AlertTriangle size={17} /><div><strong>제한사항</strong><p>{source.limitation}</p></div></div>}</div></div>}
      {tab === 'errors' && <ErrorList value={data.errors} />}
    </section>
  </div>;
}

function AssetList({ assets }: { assets: Array<Record<string, unknown>> }) { if (!assets.length) return <EmptyState title="원본 파일 기록이 없습니다" />; return <div className="asset-list">{assets.map((asset, index) => <article key={String(asset.id ?? index)}><FileKey size={18} /><div><strong>{String(asset.filename ?? asset.file_name ?? '이름 없는 파일')}</strong><small>{String(asset.sha256 ?? asset.file_hash ?? '해시 기록 없음')}</small></div><span>{formatDate(asset.collected_at as string | null)}</span></article>)}</div>; }
function Preview({ value }: { value: unknown }) { const rows = asRows(value); if (!rows.length) return <EmptyState title="안전 미리보기 자료가 없습니다" />; const columns = Array.from(new Set(rows.flatMap(Object.keys))).slice(0, 12); return <div className="table-wrap"><table><thead><tr>{columns.map((column) => <th key={column}>{column}</th>)}</tr></thead><tbody>{rows.slice(0, 20).map((row, index) => <tr key={index}>{columns.map((column) => <td key={column}>{cell(row[column])}</td>)}</tr>)}</tbody></table></div>; }
function ErrorList({ value }: { value: unknown }) { const rows = asRows(value); if (!rows.length) return <EmptyState title="기록된 오류가 없습니다" description="최근 수집과 품질 검사에서 오류가 보고되지 않았습니다." />; return <div className="error-list">{rows.map((row, index) => <article key={index}><AlertTriangle /><div><strong>{cell(row.type ?? row.code ?? '수집 오류')}</strong><p>{cell(row.message ?? row.error ?? row)}</p></div></article>)}</div>; }
function CodeBlock({ value }: { value: unknown }) { return <pre className="code-block">{JSON.stringify(value ?? null, null, 2)}</pre>; }
function cell(value: unknown) { return value === null || value === undefined ? '자료 없음' : typeof value === 'object' ? JSON.stringify(value) : String(value); }
