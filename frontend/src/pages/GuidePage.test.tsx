import { render, screen, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import { GUIDE_SECTIONS, GuidePage } from './GuidePage';

describe('GuidePage', () => {
  it('목차의 모든 절이 본문에 있고, 목차 링크는 해당 절을 가리킨다', () => {
    render(<MemoryRouter><GuidePage /></MemoryRouter>);
    const toc = screen.getByRole('navigation', { name: '사용 방법 목차' });
    for (const [id, label] of GUIDE_SECTIONS) {
      expect(within(toc).getByRole('link', { name: label })).toHaveAttribute('href', `#${id}`);
      expect(document.getElementById(id)).not.toBeNull();
    }
  });

  it('핵심 사용 흐름과 값 표시 규칙, 수집 명령을 설명한다', () => {
    render(<MemoryRouter><GuidePage /></MemoryRouter>);
    expect(screen.getAllByText(/빠진 자료 전부 수집/).length).toBeGreaterThan(0);
    expect(screen.getByText('scripts\\dss.cmd CollectAll -FromYear 2015 -ToYear 2025')).toBeInTheDocument();
    expect(screen.getByText('자료 미확보')).toBeInTheDocument();
    expect(screen.getAllByText(/0으로 채우지 않습니다/).length).toBeGreaterThan(0);
    expect(screen.getByRole('link', { name: '지역 시뮬레이션 열기' })).toHaveAttribute('href', '/area');
    expect(screen.getByText('DATA_GO_KR_SERVICE_KEY')).toBeInTheDocument();
  });
});
