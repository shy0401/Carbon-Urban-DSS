import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { Distribution, SgisGridSummaryView } from './SgisGridPanel';
import type { SgisGridSummary } from '../types';

const summary = (over: Partial<SgisGridSummary> = {}): SgisGridSummary => ({
  population: 13588, male: 6313, female: 7273, households: 5887, housing: 5838, businesses: 873, workers: 2484,
  elderly_pct: 21.6, children_pct: 9.8, single_household_pct: 31.0, old_housing_pct: 87.6, apartment_pct: null,
  housing_age: { '1979년 이전': 5, '1980년대': 915, '1990년대': 4210, '2000년대': 704, '2010년대': 25, '2020년 이후': null },
  housing_types: { 아파트: 5782, 단독주택: 28 },
  housing_area: { '40㎡ 이하': 10, '60~85㎡': 3000 },
  household_types: { '1인가구': 1823, '2세대가구': 2607 },
  sectors: [{ name: '교육서비스', businesses: 40, workers: 600 }, { name: '도소매업', businesses: 120, workers: null }],
  small_flags: [],
  ...over,
});

describe('SGIS 1km grid panel', () => {
  it('shows official totals and never turns a missing item into 0', () => {
    render(<SgisGridSummaryView summary={summary({ businesses: null })} scope="1km 격자 다마6862 전체" />);
    expect(screen.getByText('13,588 명')).toBeTruthy();
    expect(screen.getByText('5,838 호')).toBeTruthy();
    const figures = document.querySelector('.sgis-figures') as HTMLElement;
    expect(within(figures).getByText('통계 없음')).toBeTruthy(); // 사업체
    expect(screen.getAllByText('통계 없음').length).toBeGreaterThanOrEqual(3); // 2020년 이후, 도소매업 종사자
    expect(screen.getByText(/5 미만 값은 0 또는 5로 확률 대체/)).toBeTruthy();
  });
  it('explains why a share is not shown (noisy small base vs. no statistic)', () => {
    render(<SgisGridSummaryView summary={summary({ housing: 12, apartment_pct: null, elderly_pct: null, population: null })} scope="x" />);
    expect(screen.getByText('기준 20 미만이라 잡음이 커서 계산하지 않음')).toBeTruthy(); // 아파트: 주택 12호
    expect(screen.getAllByText('통계 없음').length).toBeGreaterThan(0); // 65세 이상: 인구 통계 없음
  });
  it('distribution shares are computed over present items only and keep the given order', () => {
    render(<Distribution title="주택 건축연도" rows={[['1990년대', 300], ['2000년대', 100], ['2020년 이후', null]]} unit="호" />);
    const items = screen.getAllByRole('listitem');
    expect(items.map((li) => li.querySelector('.sgis-dist-label')?.textContent)).toEqual(['1990년대', '2000년대', '2020년 이후']);
    expect(items[0].textContent).toContain('75.0%');
    expect(items[2].className).toBe('no-stat');
    expect(items[2].textContent).toContain('통계 없음');
  });
  it('flags totals that may be small-value replacements', () => {
    render(<SgisGridSummaryView summary={summary({ population: 5, small_flags: ['to_in_001'] })} scope="x" />);
    expect(screen.getByText(/5 미만일 수 있는 대체값/)).toBeTruthy();
  });
});
