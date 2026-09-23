import { PROVENANCE, type Provenance } from '../lib/provenance';

/** 근거 배지: 색 + 한글 라벨 + 테두리 모양(추정 점선, 시나리오 점, 대체 점선). DESIGN.md 5. */
export function ProvenanceBadge({ kind, detail }: { kind: Provenance; detail?: string }) {
  const item = PROVENANCE[kind];
  return <span className={`prov-badge prov-${kind}`} title={detail ? `${item.hint}: ${detail}` : item.hint}>{item.label}{detail && <span className="prov-detail">{detail}</span>}</span>;
}
