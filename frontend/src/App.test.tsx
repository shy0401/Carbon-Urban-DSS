import { render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import App from './App';

vi.mock('./components/Chart', () => ({
  Chart: ({ ariaLabel }: { ariaLabel: string }) => <div role="img" aria-label={ariaLabel} />,
}));

const dashboard = {
  selected_sector: { id: 1, name: '효자동 기준 섹터', grid_id: 'grid-1', area_m2: 10000, reason: '관측 밀도 우수' },
  electricity_kwh: 123456,
  gas_kwh: null,
  carbon_kg: 52100,
  current_far: null,
  quality: 'OBSERVED',
  monthly: [{ use_ym: '2025-01', electricity_kwh: 10000, gas_kwh: null, carbon_kg: 4300 }],
  weather: [],
  sources: [],
  coverage: { observed_months: 1, expected_months: 12 },
  regional_totals: { electricity_kwh: 987654, gas_kwh: null, carbon_kg: null },
  regional_monthly: [],
};

describe('App', () => {
  afterEach(() => vi.restoreAllMocks());

  it('대시보드 실데이터와 결측 상태를 함께 보여준다', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => Promise.resolve(new Response(JSON.stringify(dashboard), { status: 200 })));
    render(<App />);
    expect(await screen.findByText('123,456 kWh')).toBeInTheDocument();
    expect(screen.getAllByText('자료 없음').length).toBeGreaterThan(0);
    expect(screen.getByRole('navigation', { name: '주요 메뉴' })).toBeInTheDocument();
    expect(screen.getByText('987,654 kWh')).toBeInTheDocument();
  });

  it('서버 오류를 빈 값으로 숨기지 않고 재시도 가능한 상태로 표시한다', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => Promise.resolve(new Response('failed', { status: 503 })));
    render(<App />);
    await waitFor(() => expect(screen.getByText('데이터를 불러오지 못했습니다')).toBeInTheDocument());
    expect(screen.getByRole('button', { name: '다시 시도' })).toBeInTheDocument();
  });
});
