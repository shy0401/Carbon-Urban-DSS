import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { METRICS } from '../lib/mapMetrics';
import type { DongData, GridProps } from '../types';
import { DongPanel } from './DongPanel';

const data: DongData = {
  region: '41110', year: 2024, source: 'SGIS 2024 행정동',
  dongs: [
    { code: '1', name: '파장동', sigungu: '31011', population: 20000, population_status: 'OK', households: 9000, household_status: 'OK', area_km2: 4, density: 5000, cells: 2, cell_area_km2: 0.375 },
    { code: '2', name: '정자1동', sigungu: '31011', population: null, population_status: 'SUPPRESSED', households: null, household_status: 'SUPPRESSED', area_km2: 1, density: null, cells: 1, cell_area_km2: 0.125 },
  ],
  boundaries: { type: 'FeatureCollection', features: [] },
  weights: { a: [[0, 1]], b: [[0, 0.5], [1, 0.5]] },
};
const grids = new Map<string, GridProps>([
  ['a', { id: 'a', electricity_kwh_annual: 1000 } as unknown as GridProps],
  ['b', { id: 'b', electricity_kwh_annual: 400 } as unknown as GridProps],
]);
const metric = METRICS.find((m) => m.key === 'electricity_kwh_annual')!;

describe('DongPanel', () => {
  it('shows the official population and the metric summed by overlap, with a clickable comparison', () => {
    const onSelect = vi.fn();
    render(<DongPanel data={data} index={0} grids={grids} complexes={null} metric={metric} regionName="수원시" onSelect={onSelect} onClose={() => undefined} />);
    expect(screen.getByRole('heading', { name: '파장동' })).toBeInTheDocument();
    expect(screen.getByText('20,000 명')).toBeInTheDocument();
    // 1000 × 1 + 400 × 0.5
    expect(screen.getAllByText('1,200').length).toBeGreaterThan(0);
    const table = screen.getByRole('table');
    const rows = within(table).getAllByRole('row').slice(1);
    expect(rows.map((r) => within(r).getByRole('button').textContent)).toEqual(['파장동', '정자1동']);
    fireEvent.click(within(rows[1]).getByRole('button'));
    expect(onSelect).toHaveBeenCalledWith(1);
  });
  it('keeps a suppressed statistic as 비공개, not 0', () => {
    render(<DongPanel data={data} index={1} grids={grids} complexes={null} metric={metric} regionName="수원시" onSelect={() => undefined} onClose={() => undefined} />);
    expect(screen.getAllByText('비공개').length).toBe(2);
  });
});
