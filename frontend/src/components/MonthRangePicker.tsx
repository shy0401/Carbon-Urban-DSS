import { ChevronLeft, ChevronRight } from 'lucide-react';
import { useMemo, useState } from 'react';

export interface MonthRange { start: string; end: string }

const MONTHS = ['1월', '2월', '3월', '4월', '5월', '6월', '7월', '8월', '9월', '10월', '11월', '12월'];

export function monthIndex(value: string): number { const [y, m] = value.split('-').map(Number); return y * 12 + (m - 1); }
export function monthValue(index: number): string { const y = Math.floor(index / 12); const m = (index % 12) + 1; return `${y}-${String(m).padStart(2, '0')}`; }
export function monthSpan(range: MonthRange): number { return monthIndex(range.end) - monthIndex(range.start) + 1; }
/** Last fully completed month relative to ``today`` (collection never requests the running month). */
export function lastCompletedMonth(today = new Date()): string { return monthValue(today.getFullYear() * 12 + today.getMonth() - 1); }

/** Validation shared by the picker and the submit handler. Returns a Korean message or null. */
export function rangeProblem(range: MonthRange, maxMonth: string, maxSpan = 12): string | null {
  if (!/^\d{4}-\d{2}$/.test(range.start) || !/^\d{4}-\d{2}$/.test(range.end)) return '시작 월과 종료 월을 선택하세요.';
  if (monthIndex(range.start) > monthIndex(range.end)) return '시작 월은 종료 월보다 앞서야 합니다.';
  if (monthIndex(range.end) > monthIndex(maxMonth)) return `아직 끝나지 않은 달은 수집할 수 없습니다 (최대 ${maxMonth.replace('-', '.')}).`;
  if (monthSpan(range) > maxSpan) return `한 번에 최대 ${maxSpan}개월까지 요청할 수 있습니다.`;
  return null;
}

/**
 * Glass month-range picker. Click a start month, then an end month (same or another year).
 * Months after ``maxMonth`` are disabled; the span is capped at ``maxSpan``.
 */
export function MonthRangePicker({ value, onChange, maxMonth, maxSpan = 12, minYear = 2015, label = '수집 기간' }: {
  value: MonthRange; onChange: (next: MonthRange) => void; maxMonth: string; maxSpan?: number; minYear?: number; label?: string;
}) {
  const maxYear = Number(maxMonth.slice(0, 4));
  const [year, setYear] = useState(() => Number(value.end.slice(0, 4)) || maxYear);
  const [anchor, setAnchor] = useState<string | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const start = monthIndex(value.start), end = monthIndex(value.end), max = monthIndex(maxMonth);
  const problem = rangeProblem(value, maxMonth, maxSpan);
  const presets = useMemo(() => {
    const last = max; const items: Array<[string, MonthRange]> = [[`최근 ${maxSpan}개월`, { start: monthValue(last - maxSpan + 1), end: monthValue(last) }]];
    for (const y of [maxYear - 1, maxYear - 2]) if (y >= minYear) items.push([`${y}년 1~12월`, { start: `${y}-01`, end: `${y}-12` }]);
    if (monthIndex(`${maxYear}-01`) <= last) items.push([`${maxYear}년 (${Number(maxMonth.slice(5))}월까지)`, { start: `${maxYear}-01`, end: maxMonth }]);
    return items;
  }, [max, maxMonth, maxSpan, maxYear, minYear]);
  const pick = (month: string) => {
    if (!anchor) { setAnchor(month); onChange({ start: month, end: month }); return; }
    const [a, b] = monthIndex(anchor) <= monthIndex(month) ? [anchor, month] : [month, anchor];
    const capped = monthIndex(b) - monthIndex(a) + 1 > maxSpan ? monthValue(monthIndex(a) + maxSpan - 1) : b;
    onChange({ start: a, end: capped }); setAnchor(null); setHover(null);
  };
  const previewEnd = anchor && hover ? Math.max(monthIndex(anchor), monthIndex(hover)) : null;
  const previewStart = anchor && hover ? Math.min(monthIndex(anchor), monthIndex(hover)) : null;
  return <div className="range-picker" role="group" aria-label={label}>
    <div className="rp-head">
      <button type="button" className="rp-nav" aria-label="이전 연도" disabled={year <= minYear} onClick={() => setYear(year - 1)}><ChevronLeft size={17} /></button>
      <span className="rp-year" aria-live="polite">{year}년</span>
      <button type="button" className="rp-nav" aria-label="다음 연도" disabled={year >= maxYear} onClick={() => setYear(year + 1)}><ChevronRight size={17} /></button>
    </div>
    <div className="rp-months">
      {MONTHS.map((name, i) => {
        const month = `${year}-${String(i + 1).padStart(2, '0')}`; const index = year * 12 + i;
        const disabled = index > max;
        const inRange = index >= start && index <= end; const edge = index === start || index === end;
        const preview = previewStart !== null && previewEnd !== null && index >= previewStart && index <= previewEnd;
        return <button type="button" key={month} disabled={disabled} aria-pressed={inRange} aria-label={`${year}년 ${name}${disabled ? ' (수집 불가: 진행 중이거나 미래)' : ''}`}
          className={`rp-month${inRange ? ' in-range' : ''}${edge && !anchor ? ' edge' : ''}${anchor === month ? ' edge' : ''}${preview ? ' preview' : ''}`}
          onMouseEnter={() => setHover(month)} onClick={() => pick(month)}>{name}{index === max && <i className="rp-dot" aria-hidden="true" />}</button>;
      })}
    </div>
    <div className="rp-presets">{presets.map(([name, range]) => <button type="button" key={name} aria-pressed={range.start === value.start && range.end === value.end} onClick={() => { onChange(range); setAnchor(null); setYear(Number(range.end.slice(0, 4))); }}>{name}</button>)}</div>
    <div className="rp-summary"><strong>{value.start.replace('-', '.')} – {value.end.replace('-', '.')}</strong><span>{monthSpan(value) > 0 ? `${monthSpan(value)}개월` : '—'}</span></div>
    <p className={`rp-hint${problem ? ' warn' : ''}`}>{problem ?? (anchor ? '종료 월을 선택하세요.' : `시작 월 → 종료 월 순서로 누르세요. 최대 ${maxSpan}개월, ${maxMonth.replace('-', '.')}까지 완료된 달만 가능합니다.`)}</p>
  </div>;
}
