import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { StandardPanel, factorYears, type StandardRules } from './StandardPanel';

const FACTORS = [{ published: '2019-01-02', factor: 0.4594 }, { published: '2022-01-10', factor: 0.4781 }, { published: '2025-03-31', factor: 0.4541 }, { published: '2025-12-18', factor: 0.433 }];
const RULES: StandardRules = {
  version: '1.0', doc: 'docs/DATA_STANDARD.md', electricity_factors: FACTORS, gas_factor: 0.1826, gas_factor_ncv: 0.20256,
  degree_days: { rule: 'HDD 18°C · CDD 24°C', hdd_base_c: 18, cdd_base_c: 24 }, annual_rule: '12개월 모두 관측된 지번(단지)만 연간 합계', missing_rule: '없는 값은 NULL, 0과 구분',
  last_check: { version: '1.0', checked_at: '2026-10-08T01:00:00+00:00', applied_version: '1.0', summary: { OK: 1, WARN: 1 }, ok: true,
    items: [{ id: 'energy_negative', label: '건축HUB 음수 사용량은 NULL (4절)', status: 'OK', detail: '음수 행 없음', count: 0 },
            { id: 'raw_files', label: '원본은 data/raw에 그대로 (1·7절)', status: 'WARN', detail: '기록 10건, 파일 없음 1건', count: 1 }] },
};
const original = globalThis.fetch;
afterEach(() => { globalThis.fetch = original; });

function mockFetch(calls: string[]) {
  globalThis.fetch = (async (url: string, init?: RequestInit) => {
    calls.push(`${init?.method ?? 'GET'} ${url}`);
    const body = url.endsWith('/standard/check')
      ? { ...RULES.last_check, summary: { OK: 2 }, items: [{ id: 'kapt_carbon', label: 'K-apt 전력 탄소 = 사용량 × 그해 계수 (5.4절)', status: 'OK', detail: '모두 그해 계수', count: 0 }] }
      : RULES;
    return new Response(JSON.stringify(body), { status: 200, headers: { 'Content-Type': 'application/json' } });
  }) as typeof fetch;
}

describe('StandardPanel (데이터 기준)', () => {
  it('turns the publication schedule into calculation years (latest publication by year end)', () => {
    expect(factorYears(FACTORS).map((f) => `${f.years} ${f.factor}`)).toEqual(['2019~2021년 0.4594', '2022~2024년 0.4781', '2025년~ 0.433']);
  });

  it('shows the rules the code uses and the last check, and runs a new check', async () => {
    const calls: string[] = [];
    mockFetch(calls);
    render(<StandardPanel />);
    expect(await screen.findByText(/2025년~ 0.4330/)).toBeTruthy();
    expect(screen.getByText(/난방 18°C · 냉방 24°C/)).toBeTruthy();
    expect(screen.getByText('확인 필요')).toBeTruthy();
    expect(screen.getByText('기록 10건, 파일 없음 1건')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /지금 점검/ }));
    await waitFor(() => expect(screen.getByText('모두 그해 계수')).toBeTruthy());
    expect(calls).toContain('POST /api/standard/check');
  });
});
