import { fireEvent, render, screen } from '@testing-library/react';
import { useState } from 'react';
import { describe, expect, it } from 'vitest';
import { lastCompletedMonth, MonthRangePicker, monthSpan, rangeProblem, type MonthRange } from './MonthRangePicker';

describe('month range rules', () => {
  it('only completed months, start before end, at most 12 months', () => {
    expect(lastCompletedMonth(new Date(2026, 8, 23))).toBe('2026-08');
    expect(lastCompletedMonth(new Date(2026, 0, 5))).toBe('2025-12');
    expect(rangeProblem({ start: '2025-01', end: '2025-12' }, '2026-08')).toBeNull();
    expect(rangeProblem({ start: '2025-06', end: '2025-01' }, '2026-08')).toContain('앞서야');
    expect(rangeProblem({ start: '2026-01', end: '2026-09' }, '2026-08')).toContain('끝나지 않은');
    expect(rangeProblem({ start: '2024-01', end: '2025-06' }, '2026-08')).toContain('12개월');
    expect(monthSpan({ start: '2024-11', end: '2025-02' })).toBe(4);
  });
});

function Harness() {
  const [range, setRange] = useState<MonthRange>({ start: '2025-01', end: '2025-12' });
  return <><MonthRangePicker value={range} onChange={setRange} maxMonth="2026-08" /><output data-testid="value">{range.start}~{range.end}</output></>;
}

describe('MonthRangePicker', () => {
  it('picks a start then an end month and disables unfinished months', () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: '다음 연도' }));
    expect(screen.getByRole('button', { name: /2026년 9월/ })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: '2026년 3월' }));
    fireEvent.click(screen.getByRole('button', { name: '2026년 5월' }));
    expect(screen.getByTestId('value').textContent).toBe('2026-03~2026-05');
    expect(screen.getByText('3개월')).toBeTruthy();
  });
  it('offers presets for whole past years', () => {
    render(<Harness />);
    fireEvent.click(screen.getByRole('button', { name: '2024년 1~12월' }));
    expect(screen.getByTestId('value').textContent).toBe('2024-01~2024-12');
  });
});
