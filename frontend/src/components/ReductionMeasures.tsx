import { tonnes } from '../lib/plan';

/** 감축 수단 한 줄 (서버 reduction_measures, 기준 문서 5.15). 값이 null이면 계획안에 계산 근거가 없다는 뜻이다(0이 아님). */
export interface MeasureSource { label: string; url: string }
export interface MeasureRow {
  key: string; group: string; title: string; use: 'ladder' | 'alone' | 'indicator' | 'embodied'; use_label: string; indicator_text: string;
  evidence: 'measured' | 'agency' | 'calc' | 'claim' | 'assumed'; evidence_label: string; n?: string | null; apply?: string | null; base?: string | null;
  what: string; cost?: string | null; note?: string | null; sources: MeasureSource[];
  alone_kg?: number | null; alone_pct?: number | null; alone_range_kg?: number[] | null; reason?: string | null;
  reduction_kg?: number | null; reduction_pct?: number | null; reduction_range_kg?: number[] | null;
}
export interface EmbodiedBlock {
  floor_area_m2: number; kg_per_m2: number; carbon_kg: number; range_kg: number[]; years_of_operation: number | null; readymix_share_pct: number;
  options: MeasureRow[]; basis: string; source: MeasureSource;
}
export interface MeasureCatalog { measures: MeasureRow[]; embodied_measures: MeasureRow[]; embodied_basis: { kg_per_m2: number; range_kg_per_m2: number[]; readymix_share_pct: number; source: MeasureSource } }

const number = (value: number, digits = 1) => new Intl.NumberFormat('ko-KR', { minimumFractionDigits: digits, maximumFractionDigits: digits }).format(value);
/** 범위(kg 두 값)를 톤으로, 작은 감축부터. 음수는 늘어남(+). */
function rangeTons(range: number[], digits = 1) {
  const [lo, hi] = [...range].sort((a, b) => a - b);
  const sign = (v: number) => `${v < 0 ? '+' : '−'}${number(Math.abs(v) / 1000, digits)}`;
  return `${sign(lo)}~${sign(hi)} t`;
}
function evidenceText(m: MeasureRow) { return `${m.evidence_label}${m.n ? ` ${m.n}` : ''}`; }
/** 실측·기관 실적은 그대로, 계산·발표·가정은 흐리게: 근거 유형이 한눈에 갈리도록. */
function evidenceClass(m: MeasureRow) { return m.evidence === 'measured' || m.evidence === 'agency' ? 'evidence measured' : 'evidence weak'; }

function SourceLinks({ sources }: { sources: MeasureSource[] }) {
  return <>{sources.map((s, i) => <span key={s.url + s.label}>{i ? ', ' : ''}{s.url.startsWith('http') ? <a href={s.url} target="_blank" rel="noreferrer">{s.label}</a> : `${s.label}(${s.url})`}</span>)}</>;
}

function Explanations({ rows, costLabel }: { rows: MeasureRow[]; costLabel: string }) {
  return <details className="method-note measure-notes" open><summary>수단별 설명 · {costLabel} · 주의 · 출처</summary>
    <dl>{rows.map((m) => <div key={m.key}><dt>{m.title}</dt><dd>{m.what}{m.cost ? <> <b>{costLabel}:</b> {m.cost}</> : null}{m.note ? <> <b>주의:</b> {m.note}</> : null} <span className="measure-sources"><b>출처:</b> <SourceLinks sources={m.sources} /></span></dd></div>)}</dl>
  </details>;
}

/** 수단별 효과: 대책 없음에 그 수단 하나만 적용한 값. 서로 더하지 않는다(합계는 사다리). */
export function MeasuresTable({ rows }: { rows: MeasureRow[] }) {
  return <div className="report-subsection" data-testid="report-measures">
    <h3>수단별 효과 (따로 본 값, 서로 더하지 않음)</h3>
    <p>대책 없음에 그 수단 하나만 적용했을 때 줄어드는 양입니다. 같은 에너지를 줄이는 수단이 겹치므로 합하지 않고, 합계는 위 사다리로 봅니다. 값이 없는 줄은 계획안에 계산 근거가 없어 지표만 적었습니다.</p>
    <div className="table-wrap report-table"><table><thead><tr><th>수단</th><th>지표</th><th>근거</th><th className="num">이 계획안에 따로 적용하면</th><th>쓰임</th></tr></thead><tbody>
      {rows.map((m) => <tr key={m.key} className={m.use === 'ladder' ? 'in-ladder' : undefined}><th scope="row">{m.title}<small>{m.group}{m.apply ? ` · ${m.apply}` : ''}</small></th><td>{m.indicator_text}</td><td><span className={evidenceClass(m)}>{evidenceText(m)}</span></td>
        <td className="num">{m.alone_kg != null ? <>−{tonnes(m.alone_kg)}{m.alone_pct != null ? ` (−${number(m.alone_pct)}%)` : ''}{m.alone_range_kg ? <small>범위 {rangeTons(m.alone_range_kg)}</small> : null}</> : m.use === 'indicator' ? '지표만' : <>값 없음<small>{m.reason}</small></>}</td><td>{m.use_label}</td></tr>)}
    </tbody></table></div>
    <Explanations rows={rows} costLabel="비용·제도" />
  </div>;
}

/** 시공 단계 내재탄소 (참고 계산): 한 번 배출되는 양과 자재·공법 수단. 운영탄소 사다리와 합하지 않는다. */
export function EmbodiedSection({ embodied: e }: { embodied: EmbodiedBlock }) {
  return <div className="report-subsection" data-testid="report-embodied">
    <h3>시공 단계 내재탄소 (참고 계산)</h3>
    <p>지상 연면적 {number(e.floor_area_m2, 0)} m² × {number(e.kg_per_m2)} kgCO₂/m² = 약 <b>{number(e.carbon_kg / 1000, 0)} t</b> (범위 {number(e.range_kg[0] / 1000, 0)}~{number(e.range_kg[1] / 1000, 0)} t){e.years_of_operation != null ? `, 대책 없는 연간 운영탄소의 ${number(e.years_of_operation)}년치` : ''}입니다. 한 번 배출되며 운영 단계 감축으로 줄지 않습니다.</p>
    <p className="muted">{e.basis} 출처: <SourceLinks sources={[e.source]} /></p>
    <div className="table-wrap report-table"><table><thead><tr><th>자재·공법 수단</th><th>지표</th><th>근거</th><th className="num">이 계획안에 적용하면</th></tr></thead><tbody>
      {e.options.map((m) => <tr key={m.key}><th scope="row">{m.title}<small>{m.apply}</small></th><td>{m.indicator_text}</td><td><span className={evidenceClass(m)}>{evidenceText(m)}</span></td>
        <td className="num">{m.reduction_kg != null ? <>−{number(m.reduction_kg / 1000, 0)} t{m.reduction_pct != null ? ` (내재탄소의 −${number(m.reduction_pct)}%)` : ''}{m.reduction_range_kg ? <small>범위 −{number(m.reduction_range_kg[0] / 1000, 0)}~−{number(m.reduction_range_kg[1] / 1000, 0)} t</small> : null}</> : m.base ? <>값 없음<small>{m.reason}</small></> : '지표만'}</td></tr>)}
    </tbody></table></div>
    <Explanations rows={e.options} costLabel="비용" />
    <p className="muted">내재탄소 수단은 모두 설계·계산 값이라 실측 지표가 아닙니다. 운영탄소 사다리와 합하지 않습니다.</p>
  </div>;
}

/** 감축 수단 근거표: 계획안과 무관한 목록(지표·근거·적용 대상·출처). 보고서를 쓰기 전에 무엇이 들어가는지 본다. */
export function MeasureCatalogTable({ catalog }: { catalog: MeasureCatalog }) {
  const rows = [...catalog.measures, ...catalog.embodied_measures];
  return <div data-testid="measure-catalog">
    <div className="table-wrap report-table"><table><thead><tr><th>수단</th><th>지표</th><th>근거</th><th>적용 대상</th><th>보고서에서</th></tr></thead><tbody>
      {rows.map((m) => <tr key={m.key}><th scope="row">{m.title}<small>{m.group}</small></th><td>{m.indicator_text}</td><td><span className={evidenceClass(m)}>{evidenceText(m)}</span></td><td>{m.apply}</td><td>{m.use_label}</td></tr>)}
    </tbody></table></div>
    <p className="muted">내재탄소 기준: 지상 연면적 1 m²에 {number(catalog.embodied_basis.kg_per_m2)} kgCO₂({number(catalog.embodied_basis.range_kg_per_m2[0])}~{number(catalog.embodied_basis.range_kg_per_m2[1])}, 자재 생산 단계). 실측·기관 실적이 아닌 값(설계·계산, 가정)은 흐리게 적었고 기본 방안의 합계에 넣지 않습니다.</p>
  </div>;
}
