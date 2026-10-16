import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Kcsm100Panel } from './Kcsm100Panel';

afterEach(() => { vi.restoreAllMocks(); });

const feature = (x: number, y: number, props: Record<string, unknown>) => ({
  type: 'Feature', geometry: { type: 'Polygon', coordinates: [] },
  properties: { id: `g${x}_${y}`, x, y, grid500: 'cell_1000_2000', elec_t: null, status: 'missing', prev_year: 2023, prev_t: null, change_pct: null, drop: false, drop_from_t: null, ...props },
});

describe('Kcsm100Panel', () => {
  it('draws the 25 cells north-up, keeps a provider 0 as 0 and leaves absent cells empty', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      type: 'FeatureCollection',
      features: [feature(1000, 2400, { elec_t: 120, status: 'value', prev_t: 100, change_pct: 20 }), feature(1100, 2000, { elec_t: 0, status: 'zero', prev_t: 360, drop: true, drop_from_t: 360 })],
      meta: { source: 's', years: [2023, 2024], year: 2024, cells: 2, returned: 2, truncated: false, reason: null },
      summary: { cells: 2, value_cells: 1, zero_cells: 1, total_t: 120, prev_total_t: 460, drop_cells: 1, monthly: [] },
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    render(<Kcsm100Panel gridId="cell_1000_2000" year={2025} region="52110" />);
    const cells = await screen.findAllByRole('gridcell');
    expect(cells).toHaveLength(25);
    expect(String(fetchMock.mock.calls[0][0])).toContain('/api/map/kcsm100?grid=cell_1000_2000&year=2025&region=52110');
    expect(cells[0].getAttribute('aria-label')).toBe('120 tCO₂eq/년');
    expect(cells[21].getAttribute('aria-label')).toContain('0 (제공값');
    expect(cells[21].className).toContain('masked');          // 급감 표시
    expect(cells[12].className).toContain('absent');
    expect(screen.getByText(/25칸 합/).textContent).toContain('급감 1칸');
    fireEvent.click(cells[0]);
    expect(screen.getByText('2024년 전기 배출')).toBeTruthy();
  });
});
