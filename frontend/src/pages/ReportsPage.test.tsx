import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';
import { ReportsPage } from './ReportsPage';

vi.mock('../components/Chart', () => ({ Chart: () => <div role="img" aria-label="월별 차트" /> }));

const plan = {
  id: 'plan-1', label: '계획안 A', created_at: '2026-10-14T04:00:00Z', has_image: true, image_url: '/api/scenarios/plan-1/image',
  inputs: { year: 2025, grid_id: 'cell_966500_1764500', site_area: 40000, floors: 15, building_count: 10, households: 1000, population: 2500, efficiency_factor: 1, pv_ratio: 0, green_ratio: 0.3 },
  result: { gross_floor_area: 90000, total_footprint: 6000, far: 225, bcr: 15, carbon_per_person: 892.0, carbon_per_household: 2230.0, legal_status: '조례 기본 상한 이내 (1차 확인)',
    monthly: [{ use_ym: '202501', scenario: { carbon_kg: 180000 }, reference: { carbon_kg: 180000 } }],
    annual: { current: { carbon_kg: 10321305 }, scenario: { electricity_kwh: 3320137.9, gas_kwh: 4339656.2, carbon_kg: 2230040.9, electricity_carbon_kg: 1437619.7 }, reference: { electricity_kwh: 3320137.9, gas_kwh: 4339656.2, carbon_kg: 2230040.9, electricity_carbon_kg: 1437619.7 }, difference: { carbon_kg: -8091264.1 } },
    savings_pct: { electricity_kwh: 0, gas_kwh: 0, carbon_kg: 0 }, baseline_intensity: { electricity_kwh_per_m2: 36.9, gas_kwh_per_m2: 48.2 },
    zoning_check: { status: 'OK', zones: [{ zone: '제3종일반주거지역', share: 99.8, bcr_limit: 50, far_limit: 300 }], covered_share: 100, bcr_limit: 50.02, far_limit: 300.31, mixed: false, check: { label: '조례 기본 상한 이내 (1차 확인)', notes: [] } } },
};
const report = {
  id: 'r-0001-abcd', title: '탄소 시뮬레이션 검토 보고서', kind: 'PLAN', place: '전주시 송천1동 일대', year: 2025, grid_id: 'cell_966500_1764500', created_at: '2026-10-14T04:05:00Z', evidence_hash: 'deadbeef0123',
  sector: { name: '선택 격자 cell_966500_1764500' }, summary: { mode: 'TEMPLATE', model: null, paragraphs: ['2025년 전주시 송천1동 일대의 500m 분석 격자를 기준으로 작성했습니다.'], validation: '계산 엔진 근거 문장 사용' },
  sources: [{ id: 'kapt', name: 'K-apt', reference_period: '2025', collected_at: '2026-10-08T00:00:00Z' }], factors: { ELECTRICITY: { factor: 0.433, assumed: false }, GAS: { factor: 0.1826, assumed: true } },
  scenarios: [plan], facts: [], coverage: { electricity_months: 12, gas_months: 12 }, scope: '범위', totals: {}, cautions: ['계획안 결과는 1차 추정입니다.'],
  context: { facts: [{ id: 'context_admin', text: '대상 격자는 행정동 송천1동(격자의 100%, 인구 63,939명)에 걸쳐 있습니다.' }, { id: 'context_sgis_grid', text: 'SGIS 1km 격자 인구 18,317명.' }, { id: 'model_validation', text: '모델 오차 nMAE 9.4%.' }] },
};

describe('ReportsPage', () => {
  afterEach(() => vi.restoreAllMocks());

  it('시뮬레이션에서 넘어오면 그 계획안의 보고서를 바로 쓰고, 지명·핵심 결과·3D 그림을 싣되 격자 ID와 근거 해시는 싣지 않는다', async () => {
    const posts: Array<Record<string, unknown>> = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.endsWith('/api/reports') && init?.method === 'POST') { posts.push(JSON.parse(String(init.body))); return new Response(JSON.stringify(report), { status: 201 }); }
      const body = url.includes('/api/scenarios') ? [plan] : url.includes('/api/reports/engine') ? { status: 'UNAVAILABLE', model: null } : url.includes('/api/reports') ? [] : url.includes('/api/dashboard') ? { selected_sector: { grid_id: 'cell_966500_1764500' } } : {};
      return new Response(JSON.stringify(body), { status: 200 });
    });
    render(<MemoryRouter initialEntries={['/reports?scenario=plan-1&auto=1']}><ReportsPage /></MemoryRouter>);
    const paper = await screen.findByRole('heading', { name: '탄소 시뮬레이션 검토 보고서' });
    expect(posts).toHaveLength(1);
    expect(posts[0]).toMatchObject({ scenario_ids: ['plan-1'], year: 2025 });
    const article = paper.closest('article')!;
    expect(article).toHaveTextContent('전주시 송천1동 일대');
    expect(article).toHaveTextContent('1. 핵심 결과');
    expect(article).toHaveTextContent(/2,230\.0\s?tCO₂eq/);
    expect(article).toHaveTextContent('3. 계획 개요');
    expect(article).toHaveTextContent('7. 자료 출처');
    expect(screen.getByRole('img', { name: '계획안 A 3D 개념 배치' })).toBeInTheDocument();
    expect(article).toHaveTextContent('송천1동(격자의 100%');
    expect(article).not.toHaveTextContent('cell_966500_1764500');
    expect(article).not.toHaveTextContent('deadbeef0123');
    expect(article).not.toHaveTextContent('SGIS 1km');   // grid statistics and model errors stay out of the plan report
    expect(article).not.toHaveTextContent('nMAE');
    expect(article).toHaveTextContent('보고서 번호 r-0001-a');
  });
});
