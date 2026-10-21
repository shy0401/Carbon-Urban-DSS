import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { TeamModelPanel } from './TeamModelPanel';

afterEach(() => { vi.restoreAllMocks(); });

const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
const STATUS = { status: 'ready', train: '00_합본_7차', train_seconds: 120, accuracy: { model: 'm', train: 't', by_use: '주거 0.30', band_coverage: '0.81', source: '팀 인계 문서',
  test: [{ band: '1천~1만', cases: 96, median_error: 0.27, within_50pct: 0.71, sum_ratio: 1.09 }] } };
const CELL = { region: '52110', dataset: '52110_전주시', grid: 'cell_959500_1760500', scored: 1, cases: [
  { grid_id: 'cell_959500_1760500', grid_code: '다마59b60b', before_year: 2016, after_year: 2021, site_kind: 'new_site', pair_usable: true, development_id: 'd1',
    buildings_tco2e_change: 3000, model: { set: 'train_cv', actual_tco2e: 3000, pred_tco2e: 2400 } },
  { grid_id: 'cell_959500_1760500', grid_code: '다마59b60b', before_year: 2014, after_year: 2021, site_kind: 'new_site', pair_usable: true, development_id: 'd1', buildings_tco2e_change: 3100 }] };
const RESULT = { dataset: '52110_전주시', train: '00_합본_7차', snapshot: '2026-10-20', data_class: 'SCENARIO', note: 'n', combined: null, results: [{
  cell: '다마59b60b', region: null, before_year: 2021, after_year: 2024, emission_before_tco2e: 3500, floor_area_before_m2: 200000, floor_area_after_m2: 320000,
  site_kind: 'built_up', use_class: 'residential', change_tco2e: 2500, band: { q10: 900, q25: 1500, q75: 3000, q90: 4100 },
  sources_tco2e: { elec_tco2e_total: 1500, gas_tco2e_total: 1000 }, filled: ['세대수 1,080 (세대당 111 m²)'], factors: [], warnings: ['비주거 위주 계획'], out_of_range: [],
  attribution: { '연면적 변화': 2100, '전 해 배출': 200 } }] };

describe('TeamModelPanel', () => {
  it('shows the scored case of the cell and predicts a plan as a scenario with its band', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      const url = String(input);
      if (url.includes('/team-model/status')) return json(STATUS);
      if (url.includes('/team-model/cell')) return json(CELL);
      if (url.includes('/team-model/predict')) { expect(init?.method).toBe('POST'); return json(RESULT); }
      return json({}, 404);
    });
    render(<TeamModelPanel gridId="cell_959500_1760500" region="52110" />);
    expect(await screen.findByText(/학습 완료/)).toBeTruthy();
    const table = await screen.findByTestId('team-model-cases');
    expect(table.textContent).toContain('2016→2021');
    expect(table.textContent).toContain('+2,400');
    expect(table.textContent).toContain('20%');            // |2400 − 3000| ÷ 3000
    expect(table.textContent).not.toContain('2014→2021');  // only the scored pair when the cell has one
    fireEvent.change(screen.getByPlaceholderText('예: 120000'), { target: { value: '120000' } });
    fireEvent.change(screen.getByPlaceholderText('자동'), { target: { value: '1200' } });
    fireEvent.click(screen.getByRole('button', { name: '배출 변화 예측' }));
    const result = await screen.findByTestId('team-model-result');
    expect(result.textContent).toContain('+2,500');
    expect(result.textContent).toContain('+900 ~ +4,100 tCO₂e (80% 구간)');
    expect(result.textContent).toContain('전기 +1,500');
    expect(result.textContent).toContain('비주거 위주 계획');
    const call = fetchMock.mock.calls.find(([u]) => String(u).includes('/team-model/predict'));
    const body = JSON.parse(String(call?.[1]?.body));
    expect(body).toEqual({ region: '52110', plans: [{ grid: 'cell_959500_1760500', years_after: 3, new: [{ use: 'residential', floor_area_m2: 120000, dwellings: 1200 }], removed: [] }] });
  });

  it('keeps the form closed while the model is off and says why', async () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input) => String(input).includes('/status')
      ? json({ status: 'off', reason: '팀 변화 모델 서비스가 꺼져 있습니다.' }) : json({ region: '52110', dataset: null, grid: 'g', cases: [], scored: 0 }));
    render(<TeamModelPanel gridId="cell_959500_1760500" region="52110" />);
    expect(await screen.findByText('팀 변화 모델 서비스가 꺼져 있습니다.')).toBeTruthy();
    fireEvent.change(screen.getByPlaceholderText('예: 120000'), { target: { value: '5000' } });
    expect((screen.getByRole('button', { name: '배출 변화 예측' }) as HTMLButtonElement).disabled).toBe(true);
  });
});
