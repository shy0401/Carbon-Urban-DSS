import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, expect, it, vi } from 'vitest';
import { DataPage } from './DataPage';

afterEach(() => vi.restoreAllMocks());

it('외부 공급기관과 안전한 단계별 수집 범위를 선택할 수 있다', async () => {
  vi.spyOn(globalThis, 'fetch').mockImplementation((input) => {
    const url = String(input);
    return Promise.resolve(new Response(JSON.stringify(url.includes('/collections') ? [] : []), { status: 200 }));
  });
  render(<MemoryRouter><DataPage /></MemoryRouter>);
  expect(await screen.findByText('K-apt 에너지')).toBeInTheDocument();
  expect(screen.getByText('KMA ASOS')).toBeInTheDocument();
  expect(screen.getByText('SGIS 인구·가구')).toBeInTheDocument();
  expect(screen.getByText('VWorld 용도지역')).toBeInTheDocument();
  expect(screen.getByText('VWorld 연속지적')).toBeInTheDocument();
  expect(screen.getByLabelText('수집 범위')).toHaveValue('smoke');
});
