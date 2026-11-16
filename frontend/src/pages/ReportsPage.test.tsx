import { render, screen, within } from '@testing-library/react';
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
  reduction_plan: { available: true, start: { label: '대책 없음 (기준안)', carbon_kg: 2230040.9, electricity_kwh: 3320137.9, gas_kwh: 4339656.2 },
    steps: [{ key: 'envelope', title: '단열·창호 기준 강화', detail: '가스 사용을 23.6% 줄임', electricity_kwh: 3320137.9, gas_kwh: 3315497.3, carbon_kg: 2043029.5, reduction_kg: 187011.4, cumulative_pct: 8.4, range_pct: [20.5, 25.8], reduction_range_kg: [162446.0, 204444.0] },
      { key: 'rooftop_pv', title: '지붕 태양광', detail: '옥상 3,600 m²에 360.0 kW', electricity_kwh: 2224146.3, gas_kwh: 3471725.0, carbon_kg: 1597000.0, reduction_kg: 187032.7, cumulative_pct: 28.4 }],
    final_carbon_kg: 1597000.0, final_pct: 28.4, pv: { roof_m2: 3600, kw: 360, kwh: 431964 }, self_sufficiency_pct: 11.2, zeb_grade: null,
    residual: { carbon_kg: 1597000.0, offsite_pv_kw: 1853.6 }, plan: { carbon_kg: 2230040.9, pct: 0 }, assumptions: ['가정 문장.'],
    // 2026-11-16: 사다리에 넣지 않은 수단까지 하나씩 따로 본 값, 시공 단계 내재탄소(참고 계산)
    measures: [
      { key: 'envelope', group: '설계·외피', title: '단열·창호 기준 강화', use: 'ladder', use_label: '기본 방안(사다리)', indicator_text: '가스 사용량 −23.6% (−25.8~−20.5%)', evidence: 'measured', evidence_label: '실측', n: '국내 78쌍', apply: '신축·재개발', base: 'gas',
        what: '외벽·지붕 단열을 지금 기준으로 짓는다.', cost: '세대당 추가 공사비 약 130만 원.', note: '보일러 변화도 섞여 있다.', sources: [{ label: '민간 공동주택 기준 강화', url: 'https://example.org/zeb' }], alone_kg: 187011.4, alone_pct: 8.4, alone_range_kg: [162446.0, 204444.0], reason: null },
      { key: 'new_build_package', group: '설계·외피', title: '신축 통합 기준(ZEB 5등급 수준·효율등급 인증)', use: 'alone', use_label: '따로 본 값', indicator_text: '총에너지(전력·가스에 같은 비율로 적용) −11.3% (−46~+6.7%)', evidence: 'measured', evidence_label: '실측', n: '14건(국내 11)', apply: '신축·재개발', base: 'total',
        what: '인증 기준에 맞춰 한꺼번에 적용한다.', cost: '용적률 완화.', note: '단열·창호 단계와 겹친다.', sources: [{ label: '준공 시기별 실사용량', url: 'https://example.org/age' }], alone_kg: 251994.6, alone_pct: 11.3, alone_range_kg: [-149412.7, 1025818.8], reason: null },
      { key: 'elevator_regeneration', group: '설비', title: '승강기 회생제동장치', use: 'indicator', use_label: '지표만', indicator_text: '대당 연 0.39~0.57 tCO2 · 승강기 전력 −10~−30%', evidence: 'agency', evidence_label: '기관 실적', n: '서울 117대', apply: '신축·재개발·기존', base: null,
        what: '내려올 때 버리는 전기를 되돌려 쓴다.', cost: '회수 2.3~3.1년(계산).', note: '승강기 대수가 있어야 계산한다.', sources: [{ label: '서울시 배출권 승인', url: 'https://example.org/elevator' }], alone_kg: null, alone_pct: null, alone_range_kg: null, reason: '계획안에 계산 근거가 없어 지표만 적습니다.' },
      { key: 'greenery', group: '재생·상쇄', title: '녹지·조경 흡수(상쇄)', use: 'ladder', use_label: '기본 방안(사다리)', indicator_text: '녹지 1 m²에 연 1.0 kgCO2 (8.8~15.9 t/ha)', evidence: 'assumed', evidence_label: '가정', n: null, apply: '신축·재개발', base: 'green',
        what: '녹지가 흡수한다고 본다.', cost: '확인 필요.', note: '숲 기준 계수다.', sources: [{ label: '국립산림과학원 표준 탄소흡수량', url: 'docs/REDUCTION_INDICATORS.md' }], alone_kg: null, alone_pct: null, alone_range_kg: null, reason: '녹지 면적이 없습니다.' },
    ],
    embodied: { floor_area_m2: 90000, kg_per_m2: 445.4, carbon_kg: 40086000, range_kg: [30627000, 52740000], years_of_operation: 18.0, readymix_share_pct: 14.9, basis: '지상 연면적 × 국내 공동주택 자재 생산 단계 평균.', source: { label: '공동주택 27개 단지 282동', url: 'https://example.org/embodied' },
      options: [
        { key: 'low_carbon_concrete', group: '시공·자재', title: '저탄소 콘크리트(고로슬래그·플라이애시 치환)', use: 'embodied', use_label: '시공 단계(내재탄소)', indicator_text: '레미콘 몫의 배출 −12.05% (−16.3~−7.8%)', evidence: 'calc', evidence_label: '설계·계산', n: '국내 2건', apply: '신축·재개발', base: 'readymix',
          what: '시멘트 일부를 바꾼다.', cost: '확인 필요.', note: '레미콘 몫에만 적용한 값이다.', sources: [{ label: '배합 물량 기반 산정', url: 'https://example.org/concrete' }], reduction_kg: 719724.1, reduction_pct: 1.8, reduction_range_kg: [465879.5, 973568.7], reason: null },
        { key: 'modular', group: '시공·자재', title: '모듈러(공장 제작) 공법', use: 'embodied', use_label: '시공 단계(내재탄소)', indicator_text: '자재 생산 단계 배출 −35.1% (−37~−35.1%)', evidence: 'calc', evidence_label: '설계·계산', n: '국내 2건', apply: '신축(중·저층)', base: 'embodied',
          what: '유닛을 공장에서 만든다.', cost: '공사비 +28%.', note: '13층을 넘는 계획안에는 값을 계산하지 않는다.', sources: [{ label: '모듈러와 RC 비교', url: 'https://example.org/modular' }], reduction_kg: null, reduction_pct: null, reduction_range_kg: null, reason: '국내 준공 사례가 13층까지라 15층 계획안에는 값을 계산하지 않습니다.' },
        { key: 'frame_system', group: '시공·자재', title: '구조 방식 전환(벽식 → 기둥·보 라멘)', use: 'embodied', use_label: '시공 단계(내재탄소)', indicator_text: '지상 골조 자재 배출 −24.4% (−30.6~−24.4%)', evidence: 'calc', evidence_label: '설계·계산', n: '국내 1건', apply: '신축·재개발', base: null,
          what: '벽식을 라멘으로 바꾼다.', cost: '초기 공사비 +18%.', note: '전체 내재탄소에 곱할 수 없다.', sources: [{ label: '3개 동 골조 비교', url: 'https://example.org/frame' }], reduction_kg: null, reduction_pct: null, reduction_range_kg: null, reason: '전체 내재탄소에 곱할 수 없는 지표라 값은 계산하지 않습니다.' },
      ] } },
};
const catalog = { measures: plan.reduction_plan.measures, embodied_measures: plan.reduction_plan.embodied.options, embodied_basis: { kg_per_m2: 445.4, range_kg_per_m2: [340.3, 586.0], readymix_share_pct: 14.9, source: { label: '공동주택 27개 단지 282동', url: 'https://example.org/embodied' } } };
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
      const body = url.includes('/api/scenarios') ? [plan] : url.includes('/api/reports/engine') ? { status: 'UNAVAILABLE', model: null } : url.includes('/api/reports/measures') ? catalog : url.includes('/api/reports') ? [] : url.includes('/api/dashboard') ? { selected_sector: { grid_id: 'cell_966500_1764500' } } : {};
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
    expect(article).toHaveTextContent('8. 자료 출처');
    // 다른 안과 비교하지 않고 같은 계획을 줄여 가는 감축 방안
    const reduction = screen.getByTestId('report-reduction');
    expect(reduction).toHaveTextContent('5. 탄소 감축 방안');
    expect(reduction).toHaveTextContent('1. 단열·창호 기준 강화');
    expect(reduction).toHaveTextContent('근거와 가정');
    expect(screen.getByTestId('reduction-ranges')).toHaveTextContent(/단열·창호 기준 강화 20\.5~25\.8% → −162\.4\s?tCO₂eq~−204\.4\s?tCO₂eq/);   // 지표의 실측 범위와 그 단계 감축량의 폭
    expect(reduction).toHaveTextContent(/1,597\.0\s?tCO₂eq/);
    expect(reduction).toHaveTextContent('ZEB 5등급(20%) 미만');
    expect(article).not.toHaveTextContent('계획안 B');
    // 사다리 밖 수단: 하나씩 따로 본 값(합하지 않음). 계산 근거가 없는 수단은 지표만, 사다리 단계인데 입력이 없으면 '값 없음'과 이유
    const measures = screen.getByTestId('report-measures');
    expect(measures).toHaveTextContent('수단별 효과 (따로 본 값, 서로 더하지 않음)');
    const row = (name: string) => within(measures).getByRole('rowheader', { name: new RegExp(name) }).closest('tr')!;
    expect(row('신축 통합 기준')).toHaveTextContent(/−252\.0\s?tCO₂eq \(−11\.3%\)범위 \+149\.4~−1,025\.8 t/);   // 범위의 음수는 늘어남(+)
    expect(row('신축 통합 기준')).toHaveTextContent('실측 14건(국내 11)');
    expect(row('승강기 회생제동장치')).toHaveTextContent('대당 연 0.39~0.57 tCO2');
    expect(row('승강기 회생제동장치')).toHaveTextContent('지표만');
    expect(row('녹지·조경 흡수')).toHaveTextContent('값 없음녹지 면적이 없습니다.');
    expect(measures).toHaveTextContent('회수 2.3~3.1년(계산)');   // 수단별 설명·비용·주의·출처
    expect(within(measures).getByRole('link', { name: '서울시 배출권 승인' })).toHaveAttribute('href', 'https://example.org/elevator');
    // 시공 단계 내재탄소: 참고 계산으로 따로, 운영탄소 사다리와 합하지 않음
    const embodied = screen.getByTestId('report-embodied');
    expect(embodied).toHaveTextContent('90,000 m² × 445.4 kgCO₂/m² = 약 40,086 t (범위 30,627~52,740 t), 대책 없는 연간 운영탄소의 18.0년치');
    const option = (name: string) => within(embodied).getByRole('rowheader', { name: new RegExp(name) }).closest('tr')!;
    expect(option('저탄소 콘크리트')).toHaveTextContent('−720 t (내재탄소의 −1.8%)범위 −466~−974 t');
    expect(option('모듈러')).toHaveTextContent('값 없음국내 준공 사례가 13층까지라 15층 계획안에는 값을 계산하지 않습니다.');
    expect(option('구조 방식 전환')).toHaveTextContent('지표만');
    expect(embodied).toHaveTextContent('실측 지표가 아닙니다');
    // 보고서를 쓰기 전에도 수단 목록과 근거를 볼 수 있다
    expect(screen.getByTestId('measure-catalog-fold')).toHaveTextContent('운영 단계 4개 · 시공 단계 3개');
    expect(within(screen.getByTestId('measure-catalog')).getAllByRole('row', { hidden: true })).toHaveLength(8);   // 접힌 구역 안: 머리 1 + 운영 4 + 시공 3
    expect(screen.getByRole('img', { name: '계획안 A 3D 개념 배치' })).toBeInTheDocument();
    expect(article).toHaveTextContent('송천1동(격자의 100%');
    expect(article).not.toHaveTextContent('cell_966500_1764500');
    expect(article).not.toHaveTextContent('deadbeef0123');
    expect(article).not.toHaveTextContent('SGIS 1km');   // grid statistics and model errors stay out of the plan report
    expect(article).not.toHaveTextContent('nMAE');
    expect(article).toHaveTextContent('보고서 번호 r-0001-a');
  });
});
