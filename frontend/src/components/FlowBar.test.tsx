import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { FLOW_STEPS, FlowBar, flowPosition } from './FlowBar';

const at = (path: string) => render(<MemoryRouter initialEntries={[path]}><FlowBar /></MemoryRouter>);

describe('FlowBar (보는 순서)', () => {
  it('발표 순서 여섯 단계를 순서대로 보여 준다', () => {
    at('/');
    const nav = screen.getByRole('navigation', { name: '보는 순서' });
    expect(FLOW_STEPS.map((s) => s.label)).toEqual(['현황', '자료', '개발 전후', '지역별', '감축 방안', '검증']);
    expect(within(nav).getAllByRole('listitem')).toHaveLength(6);
    expect(within(nav).getByRole('link', { current: 'step' })).toHaveTextContent('현황');
    expect(within(nav).getByRole('link', { name: '다음 화면: 수집 데이터' })).toHaveAttribute('href', '/data');
    expect(within(nav).queryByRole('link', { name: /이전 화면/ })).toBeNull();
  });

  it('감축 방안 단계는 시뮬레이션 → 검토 보고서 두 화면을 차례로 넘긴다', () => {
    at('/simulation');
    expect(screen.getByRole('link', { current: 'step' })).toHaveTextContent('감축 방안');
    expect(screen.getByRole('link', { name: '다음 화면: 검토 보고서' })).toHaveAttribute('href', '/reports');
    expect(screen.getByRole('link', { name: '이전 화면: 지도 분석' })).toHaveAttribute('href', '/map');
  });

  it('주소로 단계와 넘김 위치를 찾는다', () => {
    expect(flowPosition('/')).toEqual({ step: 0, stop: 0 });
    expect(flowPosition('/data/sources/kapt')).toEqual({ step: 1, stop: 1 });
    expect(flowPosition('/regions')).toEqual({ step: 1, stop: 1 });
    expect(flowPosition('/analysis')).toEqual({ step: 3, stop: 3 });
    expect(flowPosition('/reports')).toEqual({ step: 4, stop: 5 });
    expect(flowPosition('/model')).toEqual({ step: 5, stop: 6 });
    expect(flowPosition('/guide')).toEqual({ step: -1, stop: -1 });
  });

  it('마지막 화면에는 다음이 없고, 순서에 없는 화면에서는 처음으로 가는 길을 준다', () => {
    const { unmount } = at('/model');
    expect(screen.queryByRole('link', { name: /다음 화면/ })).toBeNull();
    unmount();
    at('/guide');
    expect(screen.queryByRole('link', { current: 'step' })).toBeNull();
    expect(screen.getByRole('link', { name: '다음 화면: 대시보드' })).toHaveTextContent('처음: 대시보드');
  });
});
