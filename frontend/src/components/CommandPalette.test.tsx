import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { UiPrefsProvider } from '../hooks/useUiPrefs';
import { CommandPalette } from './CommandPalette';

function Where() { return <output data-testid="where">{useLocation().pathname}</output>; }
function setup(onClose = vi.fn()) {
  render(<UiPrefsProvider><MemoryRouter initialEntries={['/']}><Routes><Route path="*" element={<><Where /><CommandPalette open onClose={onClose} /></>} /></Routes></MemoryRouter></UiPrefsProvider>);
  return onClose;
}

describe('CommandPalette (빠른 이동)', () => {
  afterEach(() => { window.localStorage.clear(); for (const key of ['uiMode', 'theme', 'accent']) delete document.documentElement.dataset[key]; });

  it('닫혀 있으면 아무것도 그리지 않는다', () => {
    render(<MemoryRouter><CommandPalette open={false} onClose={() => undefined} /></MemoryRouter>);
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('글자를 치면 줄어들고 Enter로 그 화면에 간다', () => {
    const onClose = setup();
    const input = screen.getByRole('combobox', { name: '화면이나 설정 찾기' });
    expect(screen.getAllByRole('option').length).toBeGreaterThan(15);
    fireEvent.change(input, { target: { value: '보고서' } });
    expect(screen.getAllByRole('option')).toHaveLength(1);
    expect(screen.getByRole('option', { selected: true })).toHaveTextContent('검토 보고서');
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(onClose).toHaveBeenCalled();
    expect(screen.getByTestId('where')).toHaveTextContent('/reports');
  });

  it('화살표로 고르고, 화면 설정도 여기서 바꾼다', () => {
    setup();
    const input = screen.getByRole('combobox');
    fireEvent.change(input, { target: { value: '색 테마' } });
    expect(screen.getAllByRole('option')).toHaveLength(2);
    fireEvent.keyDown(input, { key: 'ArrowDown' });
    expect(screen.getByRole('option', { selected: true })).toHaveTextContent('색 테마: 어둡게');
    fireEvent.keyDown(input, { key: 'Enter' });
    expect(document.documentElement.dataset.theme).toBe('dark');
  });

  it('찾는 것이 없으면 안내하고, Esc로 닫는다', () => {
    const onClose = setup();
    const input = screen.getByRole('combobox');
    fireEvent.change(input, { target: { value: 'zzzz' } });
    expect(screen.queryAllByRole('option')).toHaveLength(0);
    expect(screen.getByText(/찾는 항목이 없습니다/)).toBeInTheDocument();
    fireEvent.keyDown(input, { key: 'Escape' });
    expect(onClose).toHaveBeenCalled();
  });
});
