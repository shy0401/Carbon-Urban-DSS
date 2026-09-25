import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { MissingCollection, planSentence, type MissingPlan } from './MissingCollection';

const plan = (over: Partial<MissingPlan> = {}): MissingPlan => ({
  years: [2024, 2025],
  rows: [
    { dataset: 'sgis', label: 'SGIS 행정동 인구·가구·경계', yearly: true, blocked: null, cells: [{ year: 2024, state: 'DONE', reason: '2024년 행정동 인구 34행 보유' }, { year: 2025, state: 'TODO', reason: null }] },
    { dataset: 'kapt_energy', label: 'K-apt 단지 월별 에너지', yearly: true, blocked: null, cells: [{ year: 2024, state: 'RETRY', reason: '일시 오류' }, { year: 2025, state: 'TODO', reason: null }] },
    { dataset: 'building_register', label: '건축물대장 표제부', yearly: false, blocked: '현재 공공데이터포털 키가 공급자에게 거절되었습니다.', cells: [{ year: null, state: 'BLOCKED', reason: '현재 공공데이터포털 키가 공급자에게 거절되었습니다.' }] },
  ],
  manual: [{ id: 'sgis_grid', label: 'SGIS 공식 500m 격자', why: '격자 인구', how: 'SGIS 자료제공 신청', link: 'https://sgis.kostat.go.kr/' }],
  summary: { todo: 3, done: 1, blocked: 1, manual: 1, states: { TODO: 2, RETRY: 1, DONE: 1, BLOCKED: 1 } },
  job: null,
  offline: false,
  ...over,
});

describe('MissingCollection', () => {
  afterEach(() => vi.restoreAllMocks());

  it('요약 문장은 건너뛰는 항목과 해야 할 항목을 구분한다', () => {
    expect(planSentence(plan())).toBe('수집할 항목 3개를 연도순으로 받습니다. 이미 있는 1개와 키·승인이 필요한 1개는 호출하지 않고 건너뜁니다.');
    expect(planSentence(plan({ summary: { todo: 0, done: 5, blocked: 2, manual: 1, states: {} } }))).toContain('키·승인이 필요한 항목 2개');
    expect(planSentence(plan({ summary: { todo: 0, done: 5, blocked: 0, manual: 1, states: {} } }))).toBe('자동으로 받을 수 있는 자료는 모두 수집되었습니다.');
    expect(planSentence(plan({ summary: { todo: 4, done: 2, blocked: 0, manual: 1, states: {} } }))).toBe('수집할 항목 4개를 연도순으로 받습니다. 이미 있는 2개는 호출하지 않고 건너뜁니다.');
  });

  it('빈 칸 표와 차단 사유를 보여 주고 버튼으로 전체 수집을 시작한다', async () => {
    const posts: unknown[] = [];
    vi.spyOn(globalThis, 'fetch').mockImplementation(async (input, init) => {
      if (init?.method === 'POST') { posts.push(JSON.parse(String(init.body))); return new Response(JSON.stringify({ id: 'j1', status: 'QUEUED' }), { status: 202 }); }
      return new Response(JSON.stringify(plan()));
    });
    render(<MissingCollection />);
    expect(await screen.findByText(/수집할 항목 3개/)).toBeInTheDocument();
    expect(screen.getAllByText('다시 시도').length).toBeGreaterThan(0);
    expect(screen.getAllByText('현재 공공데이터포털 키가 공급자에게 거절되었습니다.').length).toBeGreaterThan(0);
    expect(screen.getByText('SGIS 공식 500m 격자')).toBeInTheDocument();
    await userEvent.click(screen.getByTestId('collect-missing-start'));
    await waitFor(() => expect(posts).toEqual([{ from_year: 2015, to_year: 2025 }]));
  });

  it('한도 대기 중이면 자동 재개 안내와 지금 다시 시도 버튼을 보여 준다', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(plan({ job: { id: 'j1', status: 'WAITING', progress: 100, message: '09월 27일 00:20(한국 시간)에 자동으로 이어서 수집합니다.' } }))));
    render(<MissingCollection />);
    expect(await screen.findByText('한도 초과 — 자동 재개 대기')).toBeInTheDocument();
    expect(screen.getByText(/자동으로 이어서 수집합니다/)).toBeInTheDocument();
    expect(screen.getByTestId('collect-missing-start')).toHaveTextContent('지금 바로 다시 시도');
    expect(screen.getByTestId('collect-missing-start')).toBeEnabled();
  });
});
