import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { SimulationPage } from './SimulationPage';

vi.mock('../components/Chart', () => ({ Chart: () => <div role="img" aria-label="시나리오 차트" /> }));

describe('SimulationPage', () => {
  afterEach(() => vi.restoreAllMocks());

  it('기준 자료가 부족한 결과에서 null을 유지하고 서버의 사유와 가정을 표시한다', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      total_footprint: 2800,
      gross_floor_area: 33600,
      far: 336,
      bcr: 28,
      monthly: [{ use_ym: '202501', current: { electricity_kwh: null, gas_kwh: null, carbon_kg: null }, scenario: { electricity_kwh: null, gas_kwh: null, carbon_kg: null }, difference: { electricity_kwh: null, gas_kwh: null, carbon_kg: null } }],
      annual: { current: { electricity_kwh: null, gas_kwh: null, carbon_kg: null }, scenario: { electricity_kwh: null, gas_kwh: null, carbon_kg: null }, difference: { electricity_kwh: null, gas_kwh: null, carbon_kg: null } },
      quality: '기준 에너지·연면적 부족',
      assumptions: ['기준 면적과 에너지의 지번 매칭이 확보된 경우에만 추정합니다.'],
    }), { status: 200 }));
    render(<SimulationPage />);
    await userEvent.click(screen.getByRole('button', { name: '시나리오 계산' }));
    expect((await screen.findAllByText('기준 에너지·연면적 부족')).length).toBeGreaterThan(0);
    expect(screen.getByText('기준 자료가 없어 추정할 수 없습니다')).toBeInTheDocument();
    expect(screen.getByText('기준 면적과 에너지의 지번 매칭이 확보된 경우에만 추정합니다.')).toBeInTheDocument();
  });
});
