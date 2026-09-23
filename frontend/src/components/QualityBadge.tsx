import { qualityLabel, qualityTone } from '../lib/format';
import { provenanceFromCode } from '../lib/provenance';
import type { Quality } from '../types';
import { ProvenanceBadge } from './ProvenanceBadge';

/**
 * 서버의 품질·상태 값 표시. 근거 유형 코드(OBSERVED·CALCULATED·ESTIMATED·SCENARIO·FALLBACK·MISSING)는
 * 근거 배지로, 작업·모델 상태 코드는 상태 태그로, 자유 문장은 중립 태그로 그대로 보여준다.
 */
export function QualityBadge({ value, label }: { value: Quality | null | undefined; label?: string }) {
  const provenance = label ? null : provenanceFromCode(value);
  if (provenance) return <ProvenanceBadge kind={provenance} />;
  return <span className={`status-tag ${qualityTone(value)}`}>{label ?? qualityLabel(value)}</span>;
}
