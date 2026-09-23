import type { LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';
import { formatMetric, type DataClass } from '../lib/format';
import { DataClassChip } from './DataClassChip';

/**
 * Stat tile: label, value with unit, and the basis of the number (what was divided by what,
 * over how many months/parcels). Missing values stay "자료 없음" with the reason.
 */
export function MetricCard({ title, value, unit, icon: Icon, note, accent = 'teal', digits, dataClass, basis, ratio }: {
  title: string;
  value: number | null | undefined;
  unit: string;
  icon: LucideIcon;
  note?: ReactNode;
  accent?: string;
  digits?: number;
  dataClass?: DataClass;
  basis?: ReactNode;
  ratio?: number | null;
}) {
  const missing = value === null || value === undefined || !Number.isFinite(value);
  const text = formatMetric(value, '', digits ?? (unit === '%' ? 1 : 0));
  return <article className={`metric-card accent-${accent} ${missing ? 'is-missing' : ''}`}>
    <div className="metric-head"><span>{title}{dataClass && <DataClassChip value={missing ? 'MISSING' : dataClass} />}</span><span className="metric-icon"><Icon size={18} /></span></div>
    <strong className="metric-value">{missing ? '자료 없음' : <><span className="sr-only">{unit ? `${text} ${unit}` : text}</span><span aria-hidden="true">{text}</span>{unit && <small aria-hidden="true">{unit}</small>}</>}</strong>
    {typeof ratio === 'number' && Number.isFinite(ratio) && <div className="ratio-track" aria-hidden="true"><span style={{ width: `${Math.max(0, Math.min(100, ratio))}%` }} /></div>}
    {basis ? <div className="basis">{basis}</div> : <p>{note ?? (missing ? '현재 조건에서 산출할 근거 자료가 없습니다.' : '선택 섹터 기준')}</p>}
  </article>;
}
