import type { LucideIcon } from 'lucide-react';
import { formatMetric } from '../lib/format';

export function MetricCard({ title, value, unit, icon: Icon, note, accent = 'teal' }: {
  title: string;
  value: number | null | undefined;
  unit: string;
  icon: LucideIcon;
  note?: string;
  accent?: string;
}) {
  const missing = value === null || value === undefined;
  return <article className={`metric-card accent-${accent} ${missing ? 'is-missing' : ''}`}>
    <div className="metric-head"><span>{title}</span><span className="metric-icon"><Icon size={19} /></span></div>
    <strong className="metric-value">{formatMetric(value, unit, unit === '%' ? 1 : 0)}</strong>
    <p>{note ?? (missing ? '현재 조건에서 산출할 근거 자료가 없습니다.' : '선택 섹터 기준')}</p>
  </article>;
}
