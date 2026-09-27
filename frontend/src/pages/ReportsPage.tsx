import { useEffect, useState } from 'react';
import { Download, FileText, Printer, Sparkles } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import { useApi } from '../hooks/useApi';
import { useAnalysisScope } from '../hooks/useAnalysisScope';
import { api } from '../lib/api';
import { formatMetric } from '../lib/format';
import { PageHeader } from '../components/PageHeader';
import { EmptyState, LoadingState } from '../components/Status';
import { MissingValue } from '../components/MissingValue';
import { ProvenanceBadge } from '../components/ProvenanceBadge';
import { provenanceFromCode, sourceTypeLabel } from '../lib/provenance';

interface SavedScenario { id: string; created_at: string; inputs: Record<string, number | string | null>; result: Record<string, any>; has_image?: boolean; image_url?: string }
interface Fact { id: string; text: string }
interface Report { id: string; title: string; year: number; grid_id: string; created_at: string; evidence_hash: string; sector: { name: string }; summary: { mode: string; model: string | null; paragraphs: string[]; validation: string; reason?: string }; sources: Array<Record<string, any>>; scenarios: SavedScenario[]; facts: Fact[]; coverage: Record<string, number>; scope: string; totals?: Record<string, number | null>; cautions?: string[]; context?: { facts?: Fact[]; official_code?: string | null; building_energy?: Record<string, unknown> | null; model?: { best?: Record<string, { name: string; nmae: number; intensity_r2?: number | null }> } | null } }
const OVERVIEW_FACTS = new Set(['official_grid', 'context_admin', 'context_zoning', 'context_complexes', 'context_buildings', 'register', 'context_sgis_grid']);
const ENERGY_FACTS = new Set(['building_energy', 'building_intensity', 'exclusions', 'model_validation']);

/** 계획안 비교 3색 (DESIGN.md 2.6): 선택 순서대로 A·B·C. 색과 함께 이름을 항상 적는다. */
const PLAN = ['a', 'b', 'c'] as const;

export function ReportsPage() {
  const { year, gridId } = useAnalysisScope(); const scope = useApi<{ selected_sector: { grid_id: string } }>(`/dashboard?year=${year}`); const [params] = useSearchParams();
  const scenarios = useApi<SavedScenario[]>('/scenarios'); const saved = useApi<Array<{ id: string; year: number; created_at: string; grid_id: string; title?: string; scenario_count?: number }>>('/reports');
  const engine = useApi<{ status: string; model: string | null }>('/reports/engine');
  const [chosen, setChosen] = useState<string[]>([]); const [useLocal, setUseLocal] = useState(false); const [report, setReport] = useState<Report | null>(null); const [busy, setBusy] = useState(false); const [error, setError] = useState<string | null>(null);
  useEffect(() => { setChosen(params.get('scenario') ? [params.get('scenario')!] : []); setReport(null); setError(null); }, [year, gridId, params]);
  const rows = Array.isArray(scenarios.data) ? scenarios.data.filter((s) => s.inputs.type !== 'OPTIMIZATION' && Number(s.inputs.year ?? 2025) === year && (s.inputs.grid_id === (gridId || scope.data?.selected_sector?.grid_id))) : [];
  const generate = async () => { setBusy(true); setError(null); try { const r = await api<Report>('/reports', { method: 'POST', body: JSON.stringify({ year, grid_id: gridId, scenario_ids: chosen, use_local_model: useLocal }) }); setReport(r); void saved.reload(); } catch (e) { setError(e instanceof Error ? e.message : '보고서 작성 실패'); } finally { setBusy(false); } };
  const open = async (id: string) => { setBusy(true); setError(null); try { setReport(await api<Report>(`/reports/${id}`)); } catch (e) { setError(e instanceof Error ? e.message : '조회 실패'); } finally { setBusy(false); } };
  return <div className="page reports-page"><div className="no-print"><PageHeader title="도시계획 검토 보고서" description="저장된 시나리오와 출처를 고정하여 다시 확인할 수 있는 한국어 보고서를 작성합니다." />
    <section className="panel report-builder"><div className="panel-title"><h3>비교할 계획안 선택</h3><span className="status-tag">최대 3개, 같은 연도와 격자</span></div><p className="panel-description">시뮬레이션에서 계산한 계획안을 선택하세요. 선택한 순서대로 계획안 A·B·C 색을 씁니다. 계획안 없이 현재 자료 현황만 보고서로 작성할 수도 있습니다.</p>
      {scenarios.loading ? <LoadingState /> : rows.length ? <div className="scenario-picker">{rows.map((s) => { const order = chosen.indexOf(s.id); return <label key={s.id} className={order >= 0 ? `chosen plan-${PLAN[order]}` : undefined}><input type="checkbox" checked={order >= 0} disabled={order < 0 && chosen.length >= 3} onChange={(e) => setChosen(e.target.checked ? [...chosen, s.id] : chosen.filter((id) => id !== s.id))} /><span><strong>{s.inputs.floors}층 · {s.inputs.building_count}동 · 대지 {formatMetric(Number(s.inputs.site_area), 'm²')}</strong><small>{new Date(s.created_at).toLocaleString('ko-KR', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' })} 계산{s.has_image ? ' · 3D 장면 있음' : ''}{s.inputs.site_lon != null ? ' · 대지 위치 지정' : ''}</small>{s.result?.legal_status && s.result.legal_status !== '법적 상한 미확정' && <small className={String(s.result.legal_status).includes('초과') ? 'legal over' : 'legal'}>{String(s.result.legal_status)}</small>}</span>{order >= 0 && <i className="plan-chip">계획안 {PLAN[order].toUpperCase()}</i>}<b title="용적률">{formatMetric(s.result?.far, '%', 1)}</b></label>; })}</div> : <EmptyState title="이 범위에 저장된 계획안이 없습니다" description="시뮬레이션에서 계획안을 먼저 계산하거나 현재 자료 보고서를 작성하세요." />}
      {scenarios.error && <p role="alert" className="inline-error">{scenarios.error}</p>}<div className="report-actions"><label className="ai-option"><input type="checkbox" checked={useLocal} disabled={engine.data?.status !== 'READY' || busy} onChange={(e) => setUseLocal(e.target.checked)} /><Sparkles size={16} aria-hidden="true" />로컬 AI로 핵심 근거 선정<small>{engine.data?.status === 'READY' ? engine.data.model : '로컬 모델 준비 전, 기본 서식 사용 가능'}</small></label><button className="button primary" disabled={busy} onClick={() => void generate()}><FileText size={16} />{busy ? '보고서 처리 중…' : '보고서 작성'}</button></div><p className="muted">수치는 계산 엔진에서 가져옵니다. AI는 검증된 근거 문장만 선택하며 원본 수치를 다시 계산하지 않습니다.</p></section>
    {error && <p role="alert" className="inline-error">{error}</p>}
    {saved.data?.length ? <section className="report-history"><label>작성 이력<span className="select-wrap"><select aria-label="저장 보고서" value={report?.id ?? ''} onChange={(e) => e.target.value && void open(e.target.value)}><option value="">보고서 선택</option>{saved.data.map((r) => <option key={r.id} value={r.id}>{new Date(r.created_at).toLocaleString('ko-KR')} · {r.year}년 · 계획안 {r.scenario_count ?? 0}개</option>)}</select></span></label></section> : null}</div>
    {report && <><div className="report-export no-print"><span className="status-tag">{report.summary.mode === 'LOCAL_SLM' ? '로컬 AI 근거 요약' : '검증된 서식 보고서'}</span><a className="button secondary" href={`/api/reports/${report.id}/markdown`}><Download size={15} />문서 내려받기</a><button className="button secondary" onClick={() => window.print()}><Printer size={15} />인쇄 · PDF 저장</button></div>
      <article className="report-paper">
        <p className="report-kicker">Carbon Urban DSS 도시계획 검토자료</p>
        <h1>{report.title}</h1>
        <p className="report-subtitle">{report.sector?.name}, {report.year}년</p>
        <ReportTitleBlock report={report} />
        <section className="report-section"><h2>1. 검토 요약</h2>{report.summary.paragraphs.map((p, i) => <p key={i}>{p}</p>)}{report.summary.reason && <p className="muted">{report.summary.reason}</p>}</section>
        <section className="report-section"><h2>2. 대상지 개요</h2><ul className="report-list"><li>분석 단위: 500m 격자 <code>{report.grid_id}</code> (250,000m²){report.context?.official_code ? <> · SGIS 공식 500m 격자 <code>{report.context.official_code}</code></> : null}</li><li>자료 범위: 전력 {report.coverage.electricity_months}/12개월, 가스 {report.coverage.gas_months}/12개월 (공동주택 관측)</li>{(report.context?.facts ?? []).filter((f) => OVERVIEW_FACTS.has(f.id)).map((f) => <li key={f.id}>{f.text}</li>)}</ul></section>
        <section className="report-section"><h2>3. 에너지·탄소 현황</h2><ul className="report-list"><li>공동주택 관측 전력 {cellValue(report.totals?.electricity_kwh, 'kWh')}, 가스 {cellValue(report.totals?.gas_kwh, 'kWh')}, 전력 탄소 {cellValue(report.totals?.electricity_carbon_kg, 'kgCO₂eq')} (12개월 관측 지번 합계; 가스 탄소는 계수 미확정)</li>{report.facts.filter((f) => ['electricity_intensity', 'annual', 'missing'].includes(f.id)).map((f) => <li key={f.id}>{f.text}</li>)}{(report.context?.facts ?? []).filter((f) => ENERGY_FACTS.has(f.id)).map((f) => <li key={f.id}>{f.text}</li>)}</ul></section>
        <section className="report-section"><h2>4. 계획안 비교</h2>{report.scenarios.length > 0 ? <><div className="table-wrap report-table"><table><thead><tr><th>항목</th>{report.scenarios.map((s, i) => <th key={s.id} className={`num plan-col plan-${PLAN[i] ?? 'c'}`}><i className="plan-swatch" aria-hidden="true" /><span>대안 {i + 1}</span><small>계획안 {(PLAN[i] ?? '').toUpperCase()}</small>{provenanceFromCode(s.result?.data_class) && <ProvenanceBadge kind={provenanceFromCode(s.result?.data_class)!} />}</th>)}</tr></thead><tbody>{[['floors', '층수', '층'], ['building_count', '동수', '동'], ['gross_floor_area', '연면적', 'm²'], ['far', '용적률', '%'], ['bcr', '건폐율', '%'], ['households', '세대수', '세대'], ['population', '계획 인구', '명']].map(([key, label, unit]) => <tr key={key}><th>{label}</th>{report.scenarios.map((s) => <td className="num" key={s.id}>{cellValue(s.result[key] ?? s.inputs[key], unit)}</td>)}</tr>)}<tr><th>계획 연간 전력</th>{report.scenarios.map((s) => <td className="num" key={s.id}>{cellValue(s.result.annual?.scenario?.electricity_kwh, 'kWh')}</td>)}</tr><tr><th>계획 연간 가스</th>{report.scenarios.map((s) => <td className="num" key={s.id}>{cellValue(s.result.annual?.scenario?.gas_kwh, 'kWh')}</td>)}</tr><tr><th>계획 연간 전력 탄소</th>{report.scenarios.map((s) => <td className="num" key={s.id}>{cellValue(s.result.annual?.scenario?.electricity_carbon_kg, 'kgCO₂eq')}</td>)}</tr><tr><th>기준 대비 전력 탄소 변화</th>{report.scenarios.map((s) => <td className="num" key={s.id}>{cellValue(s.result.annual?.difference?.electricity_carbon_kg, 'kgCO₂eq')}</td>)}</tr><tr><th>계획 연간 전체 탄소 (전력+가스)</th>{report.scenarios.map((s) => <td className="num" key={s.id}>{cellValue(s.result.annual?.scenario?.carbon_kg, 'kgCO₂eq')}</td>)}</tr><tr><th>대지 용도지역</th>{report.scenarios.map((s) => <td className="num" key={s.id}>{zoneText(s.result.zoning_check)}</td>)}</tr><tr><th>조례 기본 상한 (건폐율/용적률)</th>{report.scenarios.map((s) => <td className="num" key={s.id}>{s.result.zoning_check?.bcr_limit != null && s.result.zoning_check?.far_limit != null ? `${s.result.zoning_check.bcr_limit}% / ${s.result.zoning_check.far_limit}%` : '판단 보류'}</td>)}</tr><tr><th>조례 상한 1차 확인</th>{report.scenarios.map((s) => <td className={`num${String(s.result.zoning_check?.check?.label ?? '').includes('초과') ? ' over' : ''}`} key={s.id}>{s.result.zoning_check?.check?.label ?? '판단 보류'}</td>)}</tr></tbody></table></div><p>계획안은 동일 격자·연도에서 비교하며, 개발부지와 수용 인구가 다르면 동등한 서비스 규모가 아닙니다.</p>{report.scenarios.some((s) => s.has_image) && <div className="report-figures">{report.scenarios.map((s, i) => s.has_image ? <figure key={s.id} className={`plan-${PLAN[i] ?? 'c'}`}><img src={s.image_url ?? `/api/scenarios/${s.id}/image`} alt={`대안 ${i + 1} 3D 개념 배치`} /><figcaption>대안 {i + 1} · 3D 개념 배치 (규모 비교용, 실제 배치안 아님. 회색 기존 건물은 층당 3m)</figcaption></figure> : null)}</div>}</> : <p>선택한 계획안 없음 (현재 자료 현황 보고서)</p>}</section>
        <section className="report-section"><h2>5. 해석 범위와 유의사항</h2><ul className="report-list">{(report.cautions?.length ? report.cautions : [report.scope, '부분 관측 합계를 완전한 연간 값으로 해석하지 않습니다. 결측 자료는 0으로 대체하지 않습니다.']).map((c) => <li key={c}>{c}</li>)}</ul></section>
        <section className="report-section"><h2>6. 데이터 출처</h2><div className="table-wrap report-table"><table><thead><tr><th>자료</th><th>기간과 수집일</th><th className="num">확보 현황</th></tr></thead><tbody>{report.sources.map((s) => <tr key={s.id}><td><strong>{s.name}</strong><small>{sourceTypeLabel(s.source_type)} 출처</small></td><td>{s.reference_period ?? '기간 미기록'}<small>{s.collected_at ? new Date(s.collected_at).toLocaleDateString('ko-KR') : '미수집'}</small></td><td className="num">{typeof s.normalized_row_count === 'number' ? formatMetric(s.normalized_row_count, '행') : <MissingValue inline />}<small>{s.status}</small></td></tr>)}</tbody></table></div></section>
        <section className="report-section"><h2>7. 재현 정보</h2><p className="hash-line">보고서 ID {report.id}<br />근거 SHA256 {report.evidence_hash}</p><p className="muted">생성 당시의 계산 결과와 출처를 보존한 보고서입니다. 이후 데이터 수집이나 설정 변경은 저장된 보고서를 변경하지 않습니다.</p></section>
      </article></>}
  </div>;
}

/** 보고서 첫 장 표제란 (DESIGN.md 4.2, 7): 분석 범위 + 근거 해시 + 생성 시각. */
function ReportTitleBlock({ report }: { report: Report }) {
  const collected = report.sources.map((s) => s.collected_at).filter((v): v is string => typeof v === 'string' && v.length >= 10).sort();
  return <dl className="report-title-block" aria-label="보고서 표제란">
    <div><dt>분석연도</dt><dd>{report.year}</dd></div>
    <div><dt>격자</dt><dd>500m 분석 격자</dd></div>
    <div><dt>선택 격자</dt><dd><code>{report.grid_id}</code></dd></div>
    <div><dt>최근 수집일</dt><dd>{collected.length ? collected[collected.length - 1].slice(0, 10) : '수집 기록 없음'}</dd></div>
    <div><dt>작성 방식</dt><dd>{report.summary.validation}</dd></div>
    <div><dt>생성 시각</dt><dd>{new Date(report.created_at).toLocaleString('ko-KR')}</dd></div>
    <div className="tb-hash"><dt>근거 해시 (SHA256)</dt><dd><code>{report.evidence_hash}</code></dd></div>
  </dl>;
}

/** 표 셀: 값이 없으면 0이 아니라 결측 표시(Number(null) = 0 방지). */
function cellValue(value: unknown, unit: string) { return typeof value === 'number' && Number.isFinite(value) ? formatMetric(value, unit, 1) : <MissingValue inline />; }

function zoneText(zc: { zones?: Array<{ zone: string | null; share: number | null }> } | null | undefined) {
  const zones = zc?.zones ?? [];
  return zones.length ? zones.slice(0, 3).map((z) => `${z.zone ?? '미상'}${z.share != null ? ` ${Math.round(z.share)}%` : ''}`).join(', ') : '자료 없음';
}
