import { useEffect, useMemo, useRef, useState } from 'react';
import { Download, FileText, Printer, Sparkles } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import { useApi } from '../hooks/useApi';
import { useAnalysisScope } from '../hooks/useAnalysisScope';
import { api } from '../lib/api';
import { formatMetric } from '../lib/format';
import { annualSide, gasCarbon, methodText, plansChartOption, savingsText, tonnes } from '../lib/plan';
import { zoningTone } from '../lib/zoning';
import { PageHeader } from '../components/PageHeader';
import { Chart } from '../components/Chart';
import { EmptyState, LoadingState } from '../components/Status';
import { MissingValue } from '../components/MissingValue';
import { ZoningSummary } from '../components/ZoningSummary';
import { PLAN_COLORS } from '../theme/palette';
import type { ScenarioResult } from '../types';

interface SavedScenario { id: string; label?: string; created_at: string; inputs: Record<string, number | string | null>; result: ScenarioResult & Record<string, any>; has_image?: boolean; image_url?: string }
interface Fact { id: string; text: string }
interface Report {
  id: string; title: string; kind?: 'PLAN' | 'STATUS'; place?: string | null; year: number; grid_id: string; created_at: string; evidence_hash: string; sector: { name: string };
  summary: { mode: string; model: string | null; paragraphs: string[]; validation: string; reason?: string };
  sources: Array<Record<string, any>>; factors?: Record<string, { factor?: number | null; assumed?: boolean; source?: string }>;
  scenarios: SavedScenario[]; facts: Fact[]; coverage: Record<string, number>; scope: string; totals?: Record<string, number | null>; cautions?: string[];
  context?: { facts?: Fact[] };
}
/** 대상지 개요에 싣는 격자 설명 (행정동, 용도지역 구성, 공동주택, 건축물대장). 격자 통계·모델 오차는 보고서에 넣지 않는다. */
const OVERVIEW_FACTS = ['context_admin', 'context_zoning', 'context_complexes', 'register'];
const GRID_ENERGY_FACTS = ['building_energy', 'building_intensity', 'exclusions'];
const PLAN = ['a', 'b', 'c'] as const;

export function ReportsPage() {
  const { year, gridId, region, regionQuery } = useAnalysisScope(); const scope = useApi<{ selected_sector: { grid_id: string } }>(`/dashboard?year=${year}${regionQuery}`); const [params] = useSearchParams();
  const scenarios = useApi<SavedScenario[]>('/scenarios'); const saved = useApi<Array<{ id: string; year: number; created_at: string; grid_id: string; title?: string; scenario_count?: number }>>('/reports');
  const engine = useApi<{ status: string; model: string | null }>('/reports/engine');
  const [chosen, setChosen] = useState<string[]>([]); const [useLocal, setUseLocal] = useState(false); const [report, setReport] = useState<Report | null>(null); const [busy, setBusy] = useState(false); const [error, setError] = useState<string | null>(null);
  const requested = params.get('scenario'); const auto = params.get('auto') === '1';
  useEffect(() => { setChosen(requested ? [requested] : []); setReport(null); setError(null); }, [year, gridId, params, requested]);
  const rows = Array.isArray(scenarios.data) ? scenarios.data.filter((s) => s.inputs.type !== 'OPTIMIZATION' && Number(s.inputs.year ?? 2025) === year && (s.inputs.grid_id === (gridId || scope.data?.selected_sector?.grid_id))) : [];
  const generate = async (ids = chosen) => { setBusy(true); setError(null); try { const r = await api<Report>('/reports', { method: 'POST', body: JSON.stringify({ year, grid_id: gridId, region, scenario_ids: ids, use_local_model: useLocal }) }); setReport(r); void saved.reload(); } catch (e) { setError(e instanceof Error ? e.message : '보고서 작성 실패'); } finally { setBusy(false); } };
  const open = async (id: string) => { setBusy(true); setError(null); try { setReport(await api<Report>(`/reports/${id}`)); } catch (e) { setError(e instanceof Error ? e.message : '조회 실패'); } finally { setBusy(false); } };
  // Coming from '보고서 작성' on the simulation screen: the report of that plan is written at once.
  const autoRun = useRef<string | null>(null);
  useEffect(() => {
    if (!auto || !requested || autoRun.current === requested || scenarios.loading) return;
    if (!rows.some((s) => s.id === requested)) return;
    autoRun.current = requested; void generate([requested]);
  }, [auto, requested, rows, scenarios.loading]); // eslint-disable-line react-hooks/exhaustive-deps
  const toggle = (id: string, on: boolean) => setChosen(on ? [...chosen, id] : chosen.filter((x) => x !== id));
  return <div className="page reports-page"><div className="no-print"><PageHeader title="검토 보고서" description="시뮬레이션에서 계산한 계획안의 에너지·탄소 결과를 대상지 정보와 함께 정리합니다. 인쇄하거나 문서로 내려받을 수 있습니다." />
    <section className="panel report-builder"><div className="panel-title"><h3>보고서에 넣을 계획안</h3><span className="status-tag">같은 대상지 · {year}년</span></div>
      <p className="panel-description">하나를 고르면 그 계획안의 보고서가 만들어지고, 둘 이상 고르면 비교표가 함께 들어갑니다 (최대 3개, 고른 순서로 A·B·C). 계획안 없이 현재 자료 현황만 쓸 수도 있습니다.</p>
      {scenarios.loading ? <LoadingState /> : rows.length ? <div className="scenario-picker">{rows.map((s) => { const order = chosen.indexOf(s.id); const sv = s.result?.savings_pct?.carbon_kg; return <label key={s.id} className={order >= 0 ? `chosen plan-${PLAN[order]}` : undefined}><input type="checkbox" checked={order >= 0} disabled={order < 0 && chosen.length >= 3} onChange={(e) => toggle(s.id, e.target.checked)} /><span><strong>{s.inputs.floors}층 · {s.inputs.building_count}동 · 연면적 {formatMetric(Number(s.result?.gross_floor_area), 'm²')}</strong><small>{new Date(s.created_at).toLocaleString('ko-KR', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })} 계산 · 연간 {tonnes(s.result?.annual?.scenario?.carbon_kg)}{typeof sv === 'number' ? ` · 기준안 대비 ${savingsText(sv)}` : ''}{s.has_image ? ' · 3D 장면 있음' : ''}</small>{s.result?.legal_status && s.result.legal_status !== '법적 상한 미확정' && <small className={String(s.result.legal_status).includes('초과') ? 'legal over' : 'legal'}>{String(s.result.legal_status)}</small>}</span>{order >= 0 && <i className="plan-chip">계획안 {PLAN[order].toUpperCase()}</i>}</label>; })}</div> : <EmptyState title="이 대상지에 계산한 계획안이 없습니다" description="시뮬레이션에서 ‘시나리오 계산’ 뒤 ‘보고서 작성’을 누르면 그 계획안의 보고서가 바로 만들어집니다." />}
      {scenarios.error && <p role="alert" className="inline-error">{scenarios.error}</p>}<div className="report-actions"><label className="ai-option"><input type="checkbox" checked={useLocal} disabled={engine.data?.status !== 'READY' || busy} onChange={(e) => setUseLocal(e.target.checked)} /><Sparkles size={16} aria-hidden="true" />로컬 AI로 요약 문장 고르기<small>{engine.data?.status === 'READY' ? engine.data.model : '로컬 모델 준비 전, 검증된 서식 사용'}</small></label><button className="button primary" disabled={busy} onClick={() => void generate()}><FileText size={16} />{busy ? '보고서 작성 중…' : chosen.length ? `보고서 작성 (계획안 ${chosen.length}개)` : '현황 보고서 작성'}</button></div><p className="muted">숫자는 모두 계산 엔진에서 가져오며, AI는 검증된 근거 문장을 고르기만 합니다.</p></section>
    {error && <p role="alert" className="inline-error">{error}</p>}
    {saved.data?.length ? <section className="report-history"><label>작성 이력<span className="select-wrap"><select aria-label="저장 보고서" value={report?.id ?? ''} onChange={(e) => e.target.value && void open(e.target.value)}><option value="">이전 보고서 열기</option>{saved.data.map((r) => <option key={r.id} value={r.id}>{new Date(r.created_at).toLocaleString('ko-KR')} · {r.year}년 · 계획안 {r.scenario_count ?? 0}개</option>)}</select></span></label></section> : null}</div>
    {report && <><div className="report-export no-print"><span className="status-tag">{report.summary.mode === 'LOCAL_SLM' ? '로컬 AI 요약 문장 선택' : '검증된 서식 보고서'}</span><a className="button secondary" href={`/api/reports/${report.id}/markdown`}><Download size={15} />문서 내려받기</a><button className="button secondary" onClick={() => window.print()}><Printer size={15} />인쇄 · PDF 저장</button></div>
      {report.scenarios.length ? <PlanReport report={report} /> : <StatusReport report={report} />}</>}
  </div>;
}

function placeOf(report: Report) { return report.place || '대상지'; }
function dateOf(value: string) { return new Date(value).toLocaleString('ko-KR', { dateStyle: 'long', timeStyle: 'short' }); }

/** 계획안 보고서: 핵심 결과 → 대상지 → 계획 개요 → 산정 → 상한 → 유의사항 → 출처. 격자 ID와 근거 해시는 싣지 않는다. */
function PlanReport({ report }: { report: Report }) {
  const plans = report.scenarios;
  const first = plans[0];
  const chart = useMemo(() => plansChartOption(plans.map((s, i) => ({ result: s.result, label: s.label ?? `계획안 ${i + 1}`, color: PLAN_COLORS[i] ?? PLAN_COLORS[2] }))), [plans]);
  const overview = (report.context?.facts ?? []).filter((f) => OVERVIEW_FACTS.includes(f.id));
  return <article className="report-paper">
    <p className="report-kicker">Carbon Urban DSS 검토 보고서</p>
    <h1>{report.title}</h1>
    <p className="report-subtitle">{placeOf(report)} · {report.year}년 기준 · 계획안 {plans.length}개</p>
    <dl className="report-title-block plan"><div><dt>대상지</dt><dd>{placeOf(report)}</dd></div><div><dt>기준연도</dt><dd>{report.year}</dd></div><div><dt>계획안</dt><dd>{plans.map((p) => p.label ?? '').join(' · ')}</dd></div><div><dt>작성일</dt><dd>{dateOf(report.created_at)}</dd></div></dl>
    <section className="report-section"><h2>1. 핵심 결과</h2>
      <div className="plan-cards">{plans.map((s, i) => { const plan = annualSide(s.result, 'scenario'); const ref = annualSide(s.result, 'reference'); const sv = s.result.savings_pct?.carbon_kg ?? null; const legal = s.result.zoning_check?.check?.label ?? s.result.legal_status; return <div key={s.id} className={`plan-card plan-${PLAN[i] ?? 'c'}`}>
        <p className="plan-card-label">{s.label ?? `계획안 ${i + 1}`}</p>
        <p className="plan-card-size">{s.inputs.floors}층 {s.inputs.building_count}동 · 연면적 {formatMetric(s.result.gross_floor_area, 'm²')} · 용적률 {formatMetric(s.result.far, '%', 1)}</p>
        <p className="plan-card-main"><span>연간 운영탄소</span><strong>{tonnes(plan?.carbon_kg)}</strong></p>
        <p className="plan-card-row"><span>기준안 대비</span><strong className={sv !== null ? (sv > 0 ? 'good' : sv < 0 ? 'bad' : '') : ''}>{savingsText(sv)}</strong><small>{ref?.carbon_kg != null ? `기준안 ${tonnes(ref.carbon_kg)}` : ''}</small></p>
        <p className="plan-card-row"><span>1인당 · 세대당</span><strong>{formatMetric(s.result.carbon_per_person, 'kg', 0)} · {formatMetric(s.result.carbon_per_household, 'kg', 0)}</strong></p>
        <p className="plan-card-row"><span>조례 상한 1차 확인</span><strong className={`legal ${zoningTone(legal ?? undefined)}`}>{legal ?? '판단 보류'}</strong></p>
      </div>; })}</div>
      {plans.some((s) => s.has_image) && <div className="report-figures">{plans.map((s, i) => s.has_image ? <figure key={s.id} className={`plan-${PLAN[i] ?? 'c'}`}><img src={s.image_url ?? `/api/scenarios/${s.id}/image`} alt={`${s.label ?? ''} 3D 개념 배치`} /><figcaption>{s.label} · 3D 개념 배치 (규모 비교용, 실제 배치안 아님)</figcaption></figure> : null)}</div>}
      {report.summary.paragraphs.map((p, i) => <p key={i}>{p}</p>)}{report.summary.reason && <p className="muted">{report.summary.reason}</p>}
    </section>
    <section className="report-section"><h2>2. 대상지 개요</h2><ul className="report-list"><li>대상지: {placeOf(report)} (500m 분석 격자 한 칸, 25만 m²), 기준연도 {report.year}</li>{overview.map((f) => <li key={f.id}>{f.text}</li>)}</ul></section>
    <section className="report-section"><h2>3. 계획 개요</h2><div className="table-wrap report-table"><table><thead><tr><th>항목</th>{plans.map((s, i) => <th key={s.id} className={`num plan-col plan-${PLAN[i] ?? 'c'}`}>{s.label}</th>)}</tr></thead><tbody>
      <tr><th>대지면적</th>{plans.map((s) => <td className="num" key={s.id}>{cellValue(s.inputs.site_area, 'm²')}</td>)}</tr>
      <tr><th>동수 · 층수</th>{plans.map((s) => <td className="num" key={s.id}>{s.inputs.building_count}동 · {s.inputs.floors}층</td>)}</tr>
      <tr><th>건축면적 합계</th>{plans.map((s) => <td className="num" key={s.id}>{cellValue(s.result.total_footprint, 'm²')}</td>)}</tr>
      <tr><th>연면적</th>{plans.map((s) => <td className="num" key={s.id}>{cellValue(s.result.gross_floor_area, 'm²')}</td>)}</tr>
      <tr><th>용적률 (상한)</th>{plans.map((s) => <td className="num" key={s.id}>{cellValue(s.result.far, '%')}{s.result.zoning_check?.far_limit != null ? <small>상한 {s.result.zoning_check.far_limit}%</small> : null}</td>)}</tr>
      <tr><th>건폐율 (상한)</th>{plans.map((s) => <td className="num" key={s.id}>{cellValue(s.result.bcr, '%')}{s.result.zoning_check?.bcr_limit != null ? <small>상한 {s.result.zoning_check.bcr_limit}%</small> : null}</td>)}</tr>
      <tr><th>세대수 · 계획 인구</th>{plans.map((s) => <td className="num" key={s.id}>{cellValue(s.inputs.households, '세대')} · {cellValue(s.inputs.population, '명')}</td>)}</tr>
      <tr><th>효율 계수</th>{plans.map((s) => <td className="num" key={s.id}>{typeof s.inputs.efficiency_factor === 'number' ? `${s.inputs.efficiency_factor.toFixed(2)}배` : <MissingValue inline />}</td>)}</tr>
      <tr><th>태양광 전력 대체율</th>{plans.map((s) => <td className="num" key={s.id}>{typeof s.inputs.pv_ratio === 'number' ? `${Math.round(s.inputs.pv_ratio * 100)}%` : <MissingValue inline />}</td>)}</tr>
      <tr><th>녹지 비율</th>{plans.map((s) => <td className="num" key={s.id}>{typeof s.inputs.green_ratio === 'number' ? `${Math.round(s.inputs.green_ratio * 100)}%` : <MissingValue inline />}</td>)}</tr>
    </tbody></table></div></section>
    <section className="report-section"><h2>4. 에너지·탄소 산정</h2>
      <div className="table-wrap report-table"><table><thead><tr><th>연간</th>{plans.map((s, i) => <th key={s.id} className={`num plan-col plan-${PLAN[i] ?? 'c'}`}>{s.label}<small>작은 글씨: 기준안 (같은 연면적, 효율 1.0·태양광 0)과 절감</small></th>)}</tr></thead><tbody>
        {([['electricity_kwh', '전력', 'kWh'], ['gas_kwh', '가스', 'kWh']] as const).map(([key, label, unit]) => <tr key={key}><th>{label}</th>{plans.map((s) => <td className="num" key={s.id}>{cellValue(annualSide(s.result, 'scenario')?.[key], unit)}<small>기준안 {formatMetric(annualSide(s.result, 'reference')?.[key], unit)} · {savingsText(s.result.savings_pct?.[key])}</small></td>)}</tr>)}
        <tr><th>전력 탄소</th>{plans.map((s) => <td className="num" key={s.id}>{tonnes(annualSide(s.result, 'scenario')?.electricity_carbon_kg)}<small>기준안 {tonnes(annualSide(s.result, 'reference')?.electricity_carbon_kg)}</small></td>)}</tr>
        <tr><th>가스 탄소 (가정 계수)</th>{plans.map((s) => <td className="num" key={s.id}>{tonnes(gasCarbon(annualSide(s.result, 'scenario')))}<small>기준안 {tonnes(gasCarbon(annualSide(s.result, 'reference')))}</small></td>)}</tr>
        <tr className="total"><th>연간 운영탄소 (전력+가스)</th>{plans.map((s) => <td className="num" key={s.id}><strong>{tonnes(annualSide(s.result, 'scenario')?.carbon_kg)}</strong><small>기준안 {tonnes(annualSide(s.result, 'reference')?.carbon_kg)} · {savingsText(s.result.savings_pct?.carbon_kg)}</small></td>)}</tr>
        <tr><th>1인당 운영탄소</th>{plans.map((s) => <td className="num" key={s.id}>{cellValue(s.result.carbon_per_person, 'kgCO₂eq')}</td>)}</tr>
        <tr><th>세대당 운영탄소</th>{plans.map((s) => <td className="num" key={s.id}>{cellValue(s.result.carbon_per_household, 'kgCO₂eq')}</td>)}</tr>
      </tbody></table></div>
      {chart && <figure className="report-chart"><Chart option={chart.option} height={240} ariaLabel="계획안과 기준안의 월별 운영탄소" /><figcaption>월별 운영탄소 ({chart.unit}) — 기준안은 점선</figcaption></figure>}
      <p className="muted">{methodText(first.result, report.factors)}</p>
    </section>
    <section className="report-section"><h2>5. 용도지역·조례 상한 확인</h2>{plans.map((s) => s.result.zoning_check ? <ZoningSummary key={s.id} zoning={s.result.zoning_check} saved compact title={`${s.label} 대지`} /> : <p key={s.id}>{s.label}: 대지와 겹치는 용도지역 자료가 없습니다.</p>)}</section>
    <section className="report-section"><h2>6. 유의사항</h2><ul className="report-list">{(report.cautions?.length ? report.cautions : [report.scope]).map((c) => <li key={c}>{c}</li>)}</ul></section>
    <SourcesSection report={report} />
    <ReportFooter report={report} />
  </article>;
}

/** 계획안 없이 쓴 현황 보고서: 격자의 관측 에너지·탄소와 대상지 설명만. */
function StatusReport({ report }: { report: Report }) {
  const context = report.context?.facts ?? [];
  const gasNote = report.totals?.gas_carbon_kg != null ? '가스 탄소는 가정 계수' : '가스 탄소는 계수 미확정';
  return <article className="report-paper">
    <p className="report-kicker">Carbon Urban DSS 검토 보고서</p>
    <h1>{report.title}</h1>
    <p className="report-subtitle">{placeOf(report)} · {report.year}년 기준</p>
    <dl className="report-title-block plan"><div><dt>대상지</dt><dd>{placeOf(report)}</dd></div><div><dt>기준연도</dt><dd>{report.year}</dd></div><div><dt>자료 범위</dt><dd>전력 {report.coverage.electricity_months}/12개월 · 가스 {report.coverage.gas_months}/12개월</dd></div><div><dt>작성일</dt><dd>{dateOf(report.created_at)}</dd></div></dl>
    <section className="report-section"><h2>1. 검토 요약</h2>{report.summary.paragraphs.map((p, i) => <p key={i}>{p}</p>)}{report.summary.reason && <p className="muted">{report.summary.reason}</p>}</section>
    <section className="report-section"><h2>2. 대상지 개요</h2><ul className="report-list"><li>대상지: {placeOf(report)} (500m 분석 격자 한 칸, 25만 m²), 기준연도 {report.year}</li>{context.filter((f) => OVERVIEW_FACTS.includes(f.id)).map((f) => <li key={f.id}>{f.text}</li>)}</ul></section>
    <section className="report-section"><h2>3. 에너지·탄소 현황</h2><ul className="report-list"><li>공동주택 관측 전력 {cellValue(report.totals?.electricity_kwh, 'kWh')}, 가스 {cellValue(report.totals?.gas_kwh, 'kWh')}, 전력 탄소 {tonnes(report.totals?.electricity_carbon_kg)}, 가스 탄소 {tonnes(report.totals?.gas_carbon_kg)} (12개월 관측 지번 합계; {gasNote})</li>{report.facts.filter((f) => ['electricity_intensity', 'annual', 'missing'].includes(f.id)).map((f) => <li key={f.id}>{f.text}</li>)}{context.filter((f) => GRID_ENERGY_FACTS.includes(f.id)).map((f) => <li key={f.id}>{f.text}</li>)}</ul></section>
    <section className="report-section"><h2>4. 계획안</h2><p>검토한 계획안이 없습니다. 시뮬레이션에서 계획안을 계산한 뒤 ‘보고서 작성’을 누르면 계획 개요·산정 표·상한 확인이 들어갑니다.</p></section>
    <section className="report-section"><h2>5. 용도지역</h2><ul className="report-list">{context.filter((f) => f.id === 'context_zoning').map((f) => <li key={f.id}>{f.text}</li>)}</ul></section>
    <section className="report-section"><h2>6. 유의사항</h2><ul className="report-list">{(report.cautions?.length ? report.cautions : [report.scope]).map((c) => <li key={c}>{c}</li>)}</ul></section>
    <SourcesSection report={report} />
    <ReportFooter report={report} />
  </article>;
}

function SourcesSection({ report }: { report: Report }) {
  const e = report.factors?.ELECTRICITY; const g = report.factors?.GAS;
  return <section className="report-section"><h2>7. 자료 출처</h2><div className="table-wrap report-table"><table><thead><tr><th>자료</th><th>기간</th><th>수집일</th></tr></thead><tbody>{report.sources.map((s) => <tr key={s.id}><td>{s.name}</td><td>{s.reference_period ?? '기간 미기록'}</td><td>{s.collected_at ? new Date(s.collected_at).toLocaleDateString('ko-KR') : '미수집'}</td></tr>)}</tbody></table></div>
    {report.factors && <p className="muted">배출계수: 전력 {e?.factor ?? '미등록'} kgCO₂eq/kWh ({e && !e.assumed ? 'GIR 승인' : '확인 필요'}), 가스 {g?.factor ?? '미등록'} kgCO₂eq/kWh ({g?.assumed ? '가정' : '등록'})</p>}
  </section>;
}

function ReportFooter({ report }: { report: Report }) {
  return <footer className="report-footer"><span>보고서 번호 {report.id.slice(0, 8)} · {dateOf(report.created_at)} 작성</span><span>숫자는 계산 엔진이 생성합니다. 작성 뒤의 수집·설정 변경은 이 보고서를 바꾸지 않습니다.</span></footer>;
}

/** 표 셀: 값이 없으면 0이 아니라 결측 표시(Number(null) = 0 방지). */
function cellValue(value: unknown, unit: string) { return typeof value === 'number' && Number.isFinite(value) ? formatMetric(value, unit, unit === '%' ? 1 : 0) : <MissingValue inline />; }
