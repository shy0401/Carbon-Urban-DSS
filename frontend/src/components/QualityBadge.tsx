import { qualityLabel, qualityTone } from '../lib/format';
import type { Quality } from '../types';

export function QualityBadge({ value, label }: { value: Quality | null | undefined; label?: string }) {
  return <span className={`badge ${qualityTone(value)}`}><span className="badge-dot" />{label ?? qualityLabel(value)}</span>;
}
