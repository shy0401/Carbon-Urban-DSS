import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { SimulationPage } from './SimulationPage';

vi.mock('../components/Chart', () => ({ Chart: () => <div role="img" aria-label="시나리오 차트" /> }));
vi.mock('../components/Massing3D', () => ({ Massing3D: () => <div aria-label="3D 개념 배치" /> }));  // WebGL is not available in jsdom

describe('SimulationPage', () => {
  afterEach(() => vi.restoreAllMocks());

  it('기준 자료가 부족한 결과에서 null을 유지하고 서버의 사유와 가정을 표시한다', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async () => new Response(JSON.stringify({
      total_footprint: 2800,
      gross_floor_area: 33600,
      far: 336,
      bcr: 28,
      monthly: [{ use_ym: '202501', current: { electricity_kwh: null, gas_kwh: null, carbon_kg: null }, scenario: { electricity_kwh: null, gas_kwh: null, carbon_kg: null }, difference: { electricity_kwh: null, gas_kwh: null, carbon_kg: null } }],
      annual: { current: { electricity_kwh: null, gas_kwh: null, carbon_kg: null }, scenario: { electricity_kwh: null, gas_kwh: null, carbon_kg: null }, difference: { electricity_kwh: null, gas_kwh: null, carbon_kg: null } },
      quality: '기준 에너지·연면적 부족',
      assumptions: ['기준 면적과 에너지의 지번 매칭이 확보된 경우에만 추정합니다.'],
    }), { status: 200 }));  // a fresh body per request (the page also reads /system)
    render(<SimulationPage />);
    await userEvent.click(screen.getByRole('button', { name: '시나리오 계산' }));
    expect((await screen.findAllByText('기준 에너지·연면적 부족')).length).toBeGreaterThan(0);
    expect(screen.getByText('기준 자료가 없어 추정할 수 없습니다')).toBeInTheDocument();
    expect(screen.getByText('기준 면적과 에너지의 지번 매칭이 확보된 경우에만 추정합니다.')).toBeInTheDocument();
  });

  it('용도지역 조례 상한 확인과 최적안 후보를 한국어 단위로 보여 주고 후보를 입력에 적용한다', async () => {
    const zoning = { status: 'OK', zones: [{ zone: '제2종일반주거지역', share: 100, bcr_limit: 60, far_limit: 250, applied_far_limit: 250 }], covered_share: 100, bcr_limit: 60, far_limit: 250, mixed: false,
      check: { label: '조례 기본 상한 초과', bcr: 'WITHIN', far: 'OVER', district_plan: true, notes: ['지구단위계획 수립 대상 규모입니다.'] },
      source: { name: '전주시 도시계획 조례', number: '제4369호', effective: '2026-04-13', url: 'https://www.law.go.kr/', checked: '2026-09-27' } };
    vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
      const url = String(input);
      const body = url.includes('/optimize')
        ? { status: 'ENERGY_OPTIMAL', legal_status: '전주시 조례 기본 상한 안의 후보만 탐색', alternatives: [{ label: '탄소 최소', floors: 9, building_count: 4, far: 252, bcr: 28, households: 300, population: 700, annual_carbon_kg: 1000 }] }
        : url.includes('/scenarios') ? { far: 336, bcr: 28, total_footprint: 2800, gross_floor_area: 33600, monthly: [], annual: { current: null, scenario: null, difference: null }, zoning_check: zoning } : {};
      return Promise.resolve(new Response(JSON.stringify(body), { status: 200 }));
    });
    render(<SimulationPage />);
    await userEvent.click(screen.getByRole('button', { name: '시나리오 계산' }));
    expect(await screen.findByText('용도지역·조례 상한 1차 확인')).toBeInTheDocument();
    expect(screen.getByText('조례 기본 상한 초과')).toBeInTheDocument();
    expect(screen.getByText('제2종일반주거지역')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '최적안 탐색' }));
    expect(await screen.findByText(/^300\s?세대$/)).toBeInTheDocument();
    expect(screen.getByText(/^700\s?명$/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: '이 조건을 입력에 적용' }));
    expect(screen.getByRole('spinbutton', { name: /층수/ })).toHaveValue(9);
  });

  it('사례 링크로 열면 링크의 입력·대지 위치로 계산하고, 링크 복사는 같은 주소를 만든다', async () => {
    const query = 'site=127.132190,35.880124,0&site_area=40000&building_count=10&footprint_per_building=600&floors=15&households=1000&population=2500&efficiency_factor=0.8&pv_ratio=0.15&green_ratio=0.3&average_household_area=84&min_households=900&min_population=2200';
    window.history.pushState({}, '', `/simulation?${query}`);
    const bodies: Array<Record<string, unknown>> = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      if (String(input).includes('/scenarios')) bodies.push(JSON.parse(String(init?.body)));
      return new Response(JSON.stringify(String(input).includes('/scenarios') ? { far: 225, bcr: 15, monthly: [], annual: { current: null, scenario: null, difference: null } } : {}), { status: 200 });
    });
    try {
      render(<SimulationPage />);
      expect(screen.getByRole('spinbutton', { name: /층수/ })).toHaveValue(15);
      expect(screen.getByRole('spinbutton', { name: /효율 계수/ })).toHaveValue(0.8);
      expect(screen.getByRole('spinbutton', { name: /최소 세대수/ })).toHaveValue(900);
      await userEvent.click(screen.getByRole('button', { name: '시나리오 계산' }));
      await waitFor(() => expect(bodies.length).toBe(1));
      expect(bodies[0]).toMatchObject({ site_area: 40000, building_count: 10, floors: 15, efficiency_factor: 0.8, pv_ratio: 0.15, site_lon: 127.13219, site_lat: 35.880124, site_rotation: 0 });
      await userEvent.click(screen.getByRole('button', { name: /링크 복사/ }));
      const link = (screen.getByLabelText(/이 조건의 링크/) as HTMLInputElement).value;
      expect(link.endsWith(`/simulation?year=2025&${query}`)).toBe(true);
    } finally {
      window.history.pushState({}, '', '/');
    }
  });
});
