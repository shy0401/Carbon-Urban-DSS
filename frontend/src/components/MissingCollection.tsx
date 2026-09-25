import { AlertTriangle, CheckCircle2, Clock, CloudDownload, ExternalLink, FileUp, KeyRound, RefreshCw } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { api } from '../lib/api';
import { formatDate } from '../lib/format';

export type CellState = 'DONE' | 'NOT_PUBLISHED' | 'TODO' | 'RETRY' | 'BLOCKED';
export interface MissingCell { year: number | null; state: CellState; reason: string | null; at?: string | null }
export interface MissingRow { dataset: string; label: string; yearly: boolean; cells: MissingCell[]; blocked: string | null }
export interface ManualSource { id: string; label: string; why: string; how: string; link: string | null }
export interface MissingJob { id: string; status: string; progress?: number | null; message?: string | null; resume_at?: string | null; created_at?: string | null; finished_at?: string | null; errors?: Array<{ dataset?: string; message?: string } | string> }
export interface MissingPlan {
  years: number[];
  rows: MissingRow[];
  manual: ManualSource[];
  summary: { todo: number; done: number; blocked: number; manual: number; states: Record<string, number> };
  job: MissingJob | null;
  offline: boolean;
}

export const CELL_LABEL: Record<CellState, string> = { DONE: '완료', NOT_PUBLISHED: '미공표', TODO: '수집 예정', RETRY: '다시 시도', BLOCKED: '키·승인 필요' };
const YEARS = Array.from({ length: 12 }, (_, i) => 2014 + i);
const ACTIVE = new Set(['QUEUED', 'RUNNING', 'WAITING']);

/** 한 줄 요약: 버튼을 누르면 무엇이 일어나는지. */
export function planSentence(plan: MissingPlan): string {
  const { todo, done, blocked } = plan.summary;
  if (!todo && !blocked) return '자동으로 받을 수 있는 자료는 모두 수집되었습니다.';
  if (!todo) return `지금 키로 더 받을 수 있는 자료가 없습니다. 키·승인이 필요한 항목 ${blocked}개를 먼저 해결하세요.`;
  const skipped = [done ? `이미 있는 ${done}개` : '', blocked ? `키·승인이 필요한 ${blocked}개` : ''].filter(Boolean);
  return `수집할 항목 ${todo}개를 연도순으로 받습니다.${skipped.length ? ` ${skipped.join('와 ')}는 호출하지 않고 건너뜁니다.` : ''}`;
}

export function isActive(job: MissingJob | null | undefined): boolean {
  return Boolean(job && ACTIVE.has(String(job.status).toUpperCase()));
}

/** 수집 데이터 화면 맨 위: 빈 칸 표 + "빠진 자료 전부 수집" 버튼 + 진행·대기 상태. */
export function MissingCollection({ onChanged }: { onChanged?: () => void }) {
  const [from, setFrom] = useState(2015);
  const [to, setTo] = useState(2025);
  const [plan, setPlan] = useState<MissingPlan | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const request = useRef<AbortController | null>(null);
  const changed = useRef(onChanged); changed.current = onChanged;

  const load = useCallback(async () => {
    request.current?.abort();
    const controller = new AbortController(); request.current = controller;
    try {
      const next = await api<MissingPlan>(`/collection/missing?from_year=${from}&to_year=${to}`, { signal: controller.signal });
      // An older API without this endpoint answers with something else: show nothing rather than a broken table.
      if (!controller.signal.aborted) { setPlan(next && Array.isArray(next.rows) && next.summary ? next : null); setError(null); }
    } catch (reason) { if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : '수집 계획을 불러오지 못했습니다.'); }
  }, [from, to]);

  useEffect(() => { void load(); return () => request.current?.abort(); }, [load]);
  const active = isActive(plan?.job);
  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => { void load(); changed.current?.(); }, 5000);
    return () => window.clearInterval(timer);
  }, [active, load]);

  const start = async () => {
    setBusy(true); setError(null);
    try { await api('/collection/missing', { method: 'POST', body: JSON.stringify({ from_year: from, to_year: to }) }); await load(); changed.current?.(); }
    catch (reason) { setError(reason instanceof Error ? reason.message : '수집을 시작하지 못했습니다.'); }
    finally { setBusy(false); }
  };

  const job = plan?.job;
  const waiting = String(job?.status ?? '').toUpperCase() === 'WAITING';
  const yearly = plan?.rows.filter((r) => r.yearly) ?? [];
  const once = plan?.rows.filter((r) => !r.yearly) ?? [];
  const blockedRows = plan?.rows.filter((r) => r.blocked && r.cells.some((c) => c.state === 'BLOCKED')) ?? [];

  return <section className="panel missing-panel" id="collect-missing" aria-labelledby="collect-missing-title">
    <div className="panel-title"><h3 id="collect-missing-title">빠진 자료 전부 수집</h3><button className="button ghost small" onClick={() => void load()}><RefreshCw size={14} />다시 확인</button></div>
    <p className="panel-description">버튼 한 번으로 아직 없는 연도·자료를 모두 받습니다. 이미 DB에 있는 자료와 키가 없는 자료는 호출하지 않고 건너뜁니다. 일일 호출 한도에 걸리면 다음 날 0시 20분(한국 시간)에 자동으로 이어서 받습니다. 수집은 이 PC의 Docker에서 실행되므로 그동안 PC와 Docker Desktop이 켜져 있어야 합니다.</p>

    <div className="missing-controls">
      <label><span>시작 연도</span><select value={from} onChange={(e) => setFrom(Number(e.target.value))} disabled={active}>{YEARS.map((y) => <option key={y} value={y}>{y}</option>)}</select></label>
      <label><span>끝 연도</span><select value={to} onChange={(e) => setTo(Number(e.target.value))} disabled={active}>{YEARS.map((y) => <option key={y} value={y}>{y}</option>)}</select></label>
      <button className="button primary" onClick={() => void start()} disabled={busy || !plan || plan.offline || (active && !waiting) || (!plan.summary.todo && !waiting)} data-testid="collect-missing-start">
        <CloudDownload size={16} />{busy ? '요청 중…' : waiting ? '지금 바로 다시 시도' : active ? '수집 중' : '빠진 자료 전부 수집 시작'}
      </button>
    </div>
    {plan && <p className="missing-sentence" role="status">{plan.offline ? '오프라인 모드라 외부 수집을 시작할 수 없습니다. 런처로 온라인 모드를 켜세요.' : planSentence(plan)}</p>}
    {error && <p className="form-error"><AlertTriangle size={15} />{error}</p>}

    {job && <div className={`missing-job ${String(job.status).toLowerCase()}`} data-testid="collect-missing-job">
      <div><strong>{jobLabel(job.status)}</strong><small>시작 {formatDate(job.created_at)}{job.finished_at ? ` · 끝 ${formatDate(job.finished_at)}` : ''}</small></div>
      {typeof job.progress === 'number' && !waiting && <div className="progress" aria-label={`진행률 ${Math.round(job.progress)}%`}><span style={{ width: `${Math.max(0, Math.min(100, job.progress))}%` }} /></div>}
      {job.message && <p>{waiting && <Clock size={14} />}{job.message}</p>}
    </div>}

    {plan && <>
      <div className="missing-legend" aria-hidden="true">{(['DONE', 'TODO', 'RETRY', 'NOT_PUBLISHED', 'BLOCKED'] as CellState[]).map((s) => <span key={s}><i className={`cell ${s.toLowerCase()}`} />{CELL_LABEL[s]}</span>)}</div>
      <div className="table-wrap missing-table">
        <table>
          <thead><tr><th>연도별 자료</th>{plan.years.map((y) => <th key={y} className="num">{y}</th>)}</tr></thead>
          <tbody>{yearly.map((row) => <tr key={row.dataset}><td><strong>{row.label}</strong></td>{row.cells.map((c) => <td key={String(c.year)} className="cell-td"><span className={`cell ${c.state.toLowerCase()}`} title={`${row.label} ${c.year}년: ${CELL_LABEL[c.state]}${c.reason ? ` — ${c.reason}` : ''}`}>{CELL_LABEL[c.state]}</span></td>)}</tr>)}</tbody>
        </table>
      </div>
      <div className="missing-once">{once.map((row) => { const c = row.cells[0]; return <article key={row.dataset}><span className={`cell ${c.state.toLowerCase()}`}>{CELL_LABEL[c.state]}</span><strong>{row.label}</strong><small>{c.reason ?? '현재 시점 자료 (연도 없음)'}</small></article>; })}</div>

      {blockedRows.length > 0 && <div className="missing-blocked"><h4><KeyRound size={15} />키·승인이 필요한 자료</h4><ul>{blockedRows.map((row) => <li key={row.dataset}><b>{row.label}</b>{row.blocked}</li>)}</ul><p className="muted">키는 PC의 <code>.env</code>에 넣고 런처를 다시 실행합니다. 공공데이터포털 키는 서비스마다 활용신청 승인이 따로 필요합니다(K-apt 에너지 15012964 · ASOS 15059093 · 건축HUB 에너지 15135963 · 건축물대장 15134735). 자세한 순서는 <a href="/guide#keys">사용 방법 → 키 설정</a>에 있습니다.</p></div>}

      <div className="missing-manual"><h4><FileUp size={15} />API로 받을 수 없는 자료 ({plan.manual.length}개)</h4><p className="muted">제공기관에 신청해 파일로 받아야 합니다. 받은 파일은 아래 <a href="#manual-upload">수동 파일 업로드</a>로 가져옵니다.</p>
        <ul>{plan.manual.map((m) => <li key={m.id}><strong>{m.label}</strong><span>{m.why}</span><small>{m.how}{m.link && <> · <a href={m.link} target="_blank" rel="noopener noreferrer">제공기관 <ExternalLink size={11} /></a></>}</small></li>)}</ul>
      </div>
      {!plan.summary.todo && !plan.summary.blocked && <p className="missing-sentence good"><CheckCircle2 size={15} />자동 수집 대상은 모두 채워졌습니다.</p>}
    </>}
  </section>;
}

function jobLabel(status: string) {
  return ({ QUEUED: '대기 중', RUNNING: '수집 중', WAITING: '한도 초과 — 자동 재개 대기', SUCCESS: '완료', PARTIAL: '완료 (남은 항목 있음)', FAILED: '실패' } as Record<string, string>)[String(status).toUpperCase()] ?? status;
}
