import { act, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { dismissLinkedRegionChange, setAnalysisScope } from '../hooks/useAnalysisScope';
import { setSystemInfo } from '../hooks/useSystemInfo';
import { LinkedRegionNotice } from './LinkedRegionNotice';

const system = {
  offline_mode: false, baseline_year: 2025, version: 't', default_region: '52110',
  region: { code: '52710', name: '전북특별자치도 완주군', short_name: '완주군', center: null },
  regions: [{ code: '52110', name: '전북특별자치도 전주시', short_name: '전주시', status: 'READY', grid_count: 10, default_grid_id: null }],
};

describe('LinkedRegionNotice (F9)', () => {
  afterEach(() => { act(() => { dismissLinkedRegionChange(); setAnalysisScope({ region: null }); }); vi.restoreAllMocks(); });

  it('링크가 분석 지역을 바꾸면 알리고 이전 지역으로 되돌릴 수 있다', () => {
    vi.spyOn(globalThis, 'fetch').mockImplementation(() => Promise.resolve(new Response(JSON.stringify(system), { status: 200 })));
    act(() => { setSystemInfo(system); setAnalysisScope({ region: null }); });
    render(<LinkedRegionNotice />);
    expect(screen.queryByTestId('linked-region-notice')).toBeNull();
    act(() => { setAnalysisScope({ region: '52710' }, { fromLink: true }); });
    expect(screen.getByTestId('linked-region-notice')).toHaveTextContent('완주군으로 바꿨습니다');
    fireEvent.click(screen.getByRole('button', { name: '전주시로 되돌리기' }));
    expect(screen.queryByTestId('linked-region-notice')).toBeNull();
  });

  it('머리에서 직접 고른 지역 변경은 알리지 않는다', () => {
    act(() => { setSystemInfo(system); setAnalysisScope({ region: '52710' }); });
    render(<LinkedRegionNotice />);
    expect(screen.queryByTestId('linked-region-notice')).toBeNull();
  });
});
