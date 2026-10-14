import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Grid100Panel } from './Grid100Panel';

afterEach(() => { vi.restoreAllMocks(); });

const feature = (x: number, y: number, props: Record<string, unknown>) => ({
  type: 'Feature', geometry: { type: 'Polygon', coordinates: [] },
  properties: { id: `g${x}_${y}`, x, y, grid500: 'cell_1000_2000', population: null, population_status: 'empty', building_count: null, floor_area_m2: null, approval_year: null, zone_class: null, ...props },
});

function mockResponse(body: unknown) {
  return vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } }));
}

describe('Grid100Panel', () => {
  it('draws 25 cells north-up, hatches masked cells and leaves cells without data empty (not 0)', async () => {
    const fetchMock = mockResponse({
      type: 'FeatureCollection',
      features: [
        feature(1000, 2400, { population: 120, population_status: 'observed', building_count: 6 }), // 북서 모서리 → 첫 칸
        feature(1100, 2000, { population: null, population_status: 'masked', building_count: 1 }),
        feature(1400, 2000, { population: null, population_status: 'empty', building_count: 3 }),
      ],
      meta: { source: '국토통계지도', years: [2016, 2024], year: 2024, cells: 3, returned: 3, truncated: false, reason: null },
      summary: { cells_with_data: 3, population_sum: 120, population_cells: 1, masked_cells: 1, buildings_sum: 10, floor_area_sum: null },
    });
    render(<Grid100Panel gridId="cell_1000_2000" year={2025} region="52110" />);
    const cells = await screen.findAllByRole('gridcell');
    expect(cells).toHaveLength(25);
    expect(String(fetchMock.mock.calls[0][0])).toContain('/api/map/grid100?grid=cell_1000_2000&year=2025&region=52110');
    expect(cells[0].getAttribute('aria-label')).toBe('120 명');
    expect(cells[21].className).toContain('masked'); // 맨 아랫줄 둘째 칸 (x+100, y+0)
    expect(cells[21].getAttribute('aria-label')).toBe('1~5명 (비공개)');
    expect(cells[24].getAttribute('aria-label')).toBe('값 없음 (0인지 미확인)');
    expect(cells[12].className).toContain('absent');
    expect((cells[12] as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/국토통계지도 2024년/)).toBeTruthy();
    expect(screen.getByText(/자료 있는 칸 3\/25/).textContent).toContain('비공개 1칸(각 1~5명)');
    fireEvent.click(cells[0]);
    expect(screen.getByText('6 동')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: '건물 수' }));
    expect(cells[21].className).not.toContain('masked');
    expect(screen.getAllByRole('gridcell')[21].getAttribute('aria-label')).toBe('1 동');
  });
  it('shows the reason when the region has no 100m data', async () => {
    mockResponse({ type: 'FeatureCollection', features: [], meta: { source: 's', years: [], year: null, cells: 0, returned: 0, truncated: false, reason: '이 지역에는 100m 격자 자료(국토통계지도)가 없습니다.' }, summary: null });
    render(<Grid100Panel gridId="cell_1000_2000" year={2025} region="11110" />);
    expect(await screen.findByText(/이 지역에는 100m 격자 자료/)).toBeTruthy();
    expect(screen.queryAllByRole('gridcell')).toHaveLength(0);
  });
  it('renders nothing for a grid id that is not a 500m cell', () => {
    const fetchMock = mockResponse({});
    const { container } = render(<Grid100Panel gridId="abc" year={2025} region={null} />);
    expect(container.textContent).toBe('');
    expect(fetchMock).not.toHaveBeenCalled();
  });
});
