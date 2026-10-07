import { CheckCircle2, Loader2, ShieldCheck } from 'lucide-react';
import { useEffect, useState } from 'react';
import { api } from '../lib/api';
import { formatDate } from '../lib/format';

export interface StandardItem { id: string; label: string; status: 'OK' | 'WARN' | 'FAIL' | 'INFO'; detail: string; count: number | null }
export interface StandardReport { version: string; checked_at: string; applied_version: string | null; summary: Record<string, number>; ok: boolean; items: StandardItem[] }
export interface StandardRules {
  version: string; doc: string;
  electricity_factors: Array<{ published: string; factor: number }>;
  gas_factor: number; gas_factor_ncv: number;
  degree_days: { rule: string; hdd_base_c: number; cdd_base_c: number };
  annual_rule: string; missing_rule: string;
  last_check: StandardReport | null;
}

const STATUS_LABEL: Record<StandardItem['status'], string> = { OK: '맞음', WARN: '확인 필요', FAIL: '어긋남', INFO: '참고' };

/** 계산 연도 범위: 공표일이 속한 해부터 다음 공표가 있는 해의 전 해까지 (그해 말까지 공표된 최신 계수). */
export function factorYears(factors: StandardRules['electricity_factors']): Array<{ years: string; factor: number }> {
  const byYear = new Map<number, number>();
  for (const f of factors) byYear.set(Number(f.published.slice(0, 4)), f.factor);
  const years = [...byYear.keys()].sort((a, b) => a - b);
  return years.map((y, i) => ({ years: i + 1 < years.length ? (years[i + 1] - 1 > y ? `${y}~${years[i + 1] - 1}년` : `${y}년`) : `${y}년~`, factor: byYear.get(y)! }));
}

/** 사용 방법 → 데이터 기준: 계산에 쓰는 기준값(코드에서 읽음)과 마지막 점검 결과. 원본 문서는 docs/DATA_STANDARD.md. */
export function StandardPanel() {
  const [rules, setRules] = useState<StandardRules | null>(null);
  const [report, setReport] = useState<StandardReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<StandardRules>('/standard').then((r) => { setRules(r); setReport(r.last_check); }).catch((e: Error) => setError(e.message));
  }, []);

  async function runCheck() {
    setBusy(true); setError(null);
    try { setReport(await api<StandardReport>('/standard/check', { method: 'POST' })); } catch (e) { setError((e as Error).message); } finally { setBusy(false); }
  }

  return <div className="standard-panel" data-testid="standard-panel">
    {rules && <div className="table-wrap guide-table"><table>
      <caption>계산에 쓰는 기준값 (기준 {rules.version}판, 코드와 같은 값)</caption>
      <tbody>
        <tr><th scope="row">전력 배출계수 (소비단, kgCO₂eq/kWh)</th><td>{factorYears(rules.electricity_factors).map((f) => `${f.years} ${f.factor.toFixed(4)}`).join(' · ')} · 2015~2018년은 계수 없음(빈칸)</td></tr>
        <tr><th scope="row">도시가스 (가정 계수)</th><td>{rules.gas_factor} kgCO₂eq/kWh (총발열량 기준 kWh로 가정, 순발열량이면 {rules.gas_factor_ncv.toFixed(4)})</td></tr>
        <tr><th scope="row">냉난방도일</th><td>난방 {rules.degree_days.hdd_base_c}°C · 냉방 {rules.degree_days.cdd_base_c}°C, 빠진 날이 있는 달은 빈칸</td></tr>
        <tr><th scope="row">연간 값</th><td>{rules.annual_rule}</td></tr>
        <tr><th scope="row">결측</th><td>{rules.missing_rule}</td></tr>
      </tbody>
    </table></div>}
    <div className="standard-check-head">
      <strong><ShieldCheck size={15} aria-hidden="true" /> 기준 점검</strong>
      {report ? <span>{formatDate(report.checked_at)} · 맞음 {report.summary.OK ?? 0} · 확인 필요 {report.summary.WARN ?? 0} · 어긋남 {report.summary.FAIL ?? 0}</span> : <span>아직 점검하지 않았습니다</span>}
      <button type="button" className="button secondary" onClick={() => void runCheck()} disabled={busy}>{busy ? <><Loader2 size={14} className="spin" aria-hidden="true" />점검 중…</> : <><CheckCircle2 size={14} aria-hidden="true" />지금 점검</>}</button>
    </div>
    {error && <p className="standard-error" role="alert">{error}</p>}
    {report && <ul className="standard-items">{report.items.map((item) => <li key={item.id} className={`standard-${item.status.toLowerCase()}`}>
      <span className="standard-status">{STATUS_LABEL[item.status]}</span><b>{item.label}</b><span>{item.detail}</span>
    </li>)}</ul>}
  </div>;
}
