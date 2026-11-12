import type { ReactNode } from 'react';
import { formatMetric } from '../lib/format';
import type { Provenance } from '../lib/provenance';
import { MissingValue } from './MissingValue';
import { ProvenanceBadge } from './ProvenanceBadge';

/**
 * 지표 카드 (DESIGN.md 5): 라벨 → 값 + 단위 → 근거 배지 + 기준.
 * 근거 배지는 서버 필드가 있을 때만 받는다. 값이 없으면 "—"와 사유, 카드 배경은 결측 해치.
 */
export function MetricCard({ title, value, unit, digits, provenance, basis, missingReason, none, ratio, dense = false, brief = false }: {
  title: string;
  value: number | null | undefined;
  unit: string;
  digits?: number;
  provenance?: Provenance | null;
  basis?: ReactNode;
  missingReason?: string;
  /** 값이 없는 것이 아니라 대상이 없음(건물 없음·단지 없음): 해치·'자료 미확보' 배지 없이 "—"와 이 문구만. */
  none?: string;
  ratio?: number | null;
  /** 지도 옆 패널의 2열 밀집형. */
  dense?: boolean;
  /** 한눈에 보는 요약 카드: 기준 문구를 한 줄로 줄인다(긴 산식은 화면의 '산식과 근거' 접이식에 둔다). */
  brief?: boolean;
}) {
  const empty = value === null || value === undefined || !Number.isFinite(value);
  const notApplicable = empty && Boolean(none);
  const missing = empty && !notApplicable;
  // 소수 자리를 정해 준 카드는 늘 그 자리수로(39.0 · 48.5).
  const text = formatMetric(value, '', digits ?? (unit === '%' ? 1 : 0), digits !== undefined);
  return <article className={`metric-card${dense ? ' dense' : ''}${brief ? ' brief' : ''}${missing ? ' is-missing' : ''}${notApplicable ? ' is-none' : ''}`}>
    <h3 className="metric-label">{title}</h3>
    <p className="metric-value">{notApplicable ? <span className="missing-value none"><span className="mv-dash" aria-hidden="true">—</span><span className="sr-only">해당 없음</span><span className="mv-reason">{none}</span></span> : missing ? <MissingValue reason={missingReason ?? '현재 조건에서 산출할 근거 자료가 없습니다.'} /> : <><span className="sr-only">{unit ? `${text} ${unit}` : text}</span><span aria-hidden="true">{text}</span>{unit && <span className="unit" aria-hidden="true">{unit}</span>}</>}</p>
    {!empty && typeof ratio === 'number' && Number.isFinite(ratio) && <div className="ratio-track" aria-hidden="true"><span style={{ width: `${Math.max(0, Math.min(100, ratio))}%` }} /></div>}
    {!notApplicable && (provenance || missing || basis) && <div className="metric-foot">{missing ? <ProvenanceBadge kind="missing" /> : provenance && <ProvenanceBadge kind={provenance} />}{basis && !missing && <span className="metric-basis">{basis}</span>}</div>}
  </article>;
}
