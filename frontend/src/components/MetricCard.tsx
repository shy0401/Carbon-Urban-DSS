import type { ReactNode } from 'react';
import { formatMetric } from '../lib/format';
import type { Provenance } from '../lib/provenance';
import { MissingValue } from './MissingValue';
import { ProvenanceBadge } from './ProvenanceBadge';

/**
 * 지표 카드 (DESIGN.md 5): 라벨 → 값 + 단위 → 근거 배지 + 기준.
 * 근거 배지는 서버 필드가 있을 때만 받는다. 값이 없으면 "—"와 사유, 카드 배경은 결측 해치.
 */
export function MetricCard({ title, value, unit, digits, provenance, basis, missingReason, ratio, dense = false }: {
  title: string;
  value: number | null | undefined;
  unit: string;
  digits?: number;
  provenance?: Provenance | null;
  basis?: ReactNode;
  missingReason?: string;
  ratio?: number | null;
  /** 지도 옆 패널의 2열 밀집형. */
  dense?: boolean;
}) {
  const missing = value === null || value === undefined || !Number.isFinite(value);
  const text = formatMetric(value, '', digits ?? (unit === '%' ? 1 : 0));
  return <article className={`metric-card${dense ? ' dense' : ''}${missing ? ' is-missing' : ''}`}>
    <h3 className="metric-label">{title}</h3>
    <p className="metric-value">{missing ? <MissingValue reason={missingReason ?? '현재 조건에서 산출할 근거 자료가 없습니다.'} /> : <><span className="sr-only">{unit ? `${text} ${unit}` : text}</span><span aria-hidden="true">{text}</span>{unit && <span className="unit" aria-hidden="true">{unit}</span>}</>}</p>
    {!missing && typeof ratio === 'number' && Number.isFinite(ratio) && <div className="ratio-track" aria-hidden="true"><span style={{ width: `${Math.max(0, Math.min(100, ratio))}%` }} /></div>}
    {(provenance || missing || basis) && <div className="metric-foot">{missing ? <ProvenanceBadge kind="missing" /> : provenance && <ProvenanceBadge kind={provenance} />}{basis && !missing && <span className="metric-basis">{basis}</span>}</div>}
  </article>;
}
