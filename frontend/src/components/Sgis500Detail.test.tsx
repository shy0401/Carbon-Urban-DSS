import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { GridProps } from '../types';
import { PopulationSpark, Sgis500Detail } from './Sgis500Detail';

afterEach(() => { vi.restoreAllMocks(); });

describe('Sgis500Detail', () => {
  it('shows nothing until the 500m statistics are loaded, and "no statistic" (not 0) for a cell without a row', () => {
    const { container, rerender } = render(<Sgis500Detail p={{ id: 'cell_1_1' } as GridProps} />);
    expect(container.textContent).toBe('');
    rerender(<Sgis500Detail p={{ id: 'cell_1_1', sgis500_status: 'NO_STAT', sgis500_year: 2024 } as unknown as GridProps} />);
    expect(screen.getByText(/공표된 통계가 없습니다/)).toBeTruthy();
    expect(container.textContent).toContain('0이 아닙니다');
  });
  it('lists the values, the change since 2015 and the years from the API', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      code: '다마62a48a', years: [2010, 2015, 2024], source: 's', note: 'n',
      series: [{ year: 2010, population: 90, households: null, housing: null, workers: null }, { year: 2015, population: 100, households: 40, housing: 38, workers: 10 },
        { year: 2024, population: 120, households: 48, housing: 40, workers: null }],
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }));
    const p = { id: 'cell_962000_1748000', sgis500_status: 'OBSERVED', sgis500_year: 2024, sgis500_population: 120, sgis500_pop_density: 480, sgis500_households: 48,
      sgis500_housing: 40, sgis500_workers: null, sgis500_base_year: 2015, sgis500_base_population: 100, sgis500_pop_change_pct: 20, sgis500_small: [] } as unknown as GridProps;
    render(<Sgis500Detail p={p} />);
    expect(screen.getByText('인구 증감 (2015→2024)')).toBeTruthy();
    expect(screen.getByText('밀도 480 명/km²')).toBeTruthy();
    expect(await screen.findByText('연도별 값 (3개 연도)')).toBeTruthy();
    expect(String(fetchMock.mock.calls[0][0])).toContain('/api/sgis-grid/500m/cell/cell_962000_1748000');
  });
  it('draws the population line only through years with a value', () => {
    const { container } = render(<PopulationSpark rows={[{ year: 2010, population: 90 }, { year: 2015, population: null }, { year: 2024, population: 120 }] as never} />);
    expect(container.querySelectorAll('circle')).toHaveLength(2);
    expect(container.textContent).toContain('2024년 120 명');
  });
});
