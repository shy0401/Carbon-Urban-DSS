import { fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { UiPrefsProvider } from '../hooks/useUiPrefs';
import { UI_PREFS_STORAGE_KEY } from '../lib/uiPrefs';
import { Fold, Note } from './Fold';
import { UiSettings } from './UiSettings';

const html = () => document.documentElement.dataset;

describe('UiSettings (사이트에서 바로 바꾸는 화면 설정)', () => {
  afterEach(() => { window.localStorage.clear(); for (const key of ['uiMode', 'theme', 'accent']) delete document.documentElement.dataset[key]; });

  it('단추를 누르면 설정 창이 열리고, 고르는 즉시 <html> 속성과 저장소에 반영된다', () => {
    render(<UiPrefsProvider><UiSettings /></UiPrefsProvider>);
    expect(html()).toMatchObject({ uiMode: 'brief', theme: 'light', accent: 'green' });
    expect(screen.queryByRole('dialog', { name: '화면 설정' })).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: '화면 설정' }));
    const panel = screen.getByRole('dialog', { name: '화면 설정' });
    expect(within(panel).getByRole('radio', { name: '요약' })).toBeChecked();
    fireEvent.click(within(panel).getByRole('radio', { name: '발표' }));
    fireEvent.click(within(panel).getByRole('radio', { name: '어둡게' }));
    fireEvent.click(within(panel).getByRole('radio', { name: '남색' }));
    expect(html()).toMatchObject({ uiMode: 'present', theme: 'dark', accent: 'navy' });
    expect(JSON.parse(window.localStorage.getItem(UI_PREFS_STORAGE_KEY) ?? '{}')).toEqual({ mode: 'present', theme: 'dark', accent: 'navy' });
    expect(within(panel).getByRole('status')).toHaveTextContent('글자를 키우고');
  });

  it('처음 설정으로 되돌리고, Esc로 닫는다', () => {
    render(<UiPrefsProvider initial={{ mode: 'detail', theme: 'dark', accent: 'ink' }}><UiSettings /></UiPrefsProvider>);
    fireEvent.click(screen.getByRole('button', { name: '화면 설정' }));
    fireEvent.click(screen.getByRole('button', { name: '처음 설정으로' }));
    expect(html()).toMatchObject({ uiMode: 'brief', theme: 'light', accent: 'green' });
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog', { name: '화면 설정' })).toBeNull();
    expect(screen.getByRole('button', { name: '화면 설정' })).toHaveAttribute('aria-expanded', 'false');
  });

  it("보기 방식 '상세'는 접힌 근거와 설명을 펼치고, '요약'으로 돌아오면 처음 상태로 접는다", () => {
    render(<UiPrefsProvider><UiSettings /><Fold title="근거 표" testId="fold-x"><p>표</p></Fold><Fold title="열어 둔 것" defaultOpen testId="fold-y"><p>그림</p></Fold><Note label="읽는 법">설명 글</Note></UiPrefsProvider>);
    const fold = screen.getByTestId('fold-x') as HTMLDetailsElement;
    const kept = screen.getByTestId('fold-y') as HTMLDetailsElement;
    const note = screen.getByText('설명 글').closest('details') as HTMLDetailsElement;
    expect([fold.open, kept.open, note.open]).toEqual([false, true, false]);
    fireEvent.click(screen.getByRole('button', { name: '화면 설정' }));
    fireEvent.click(screen.getByRole('radio', { name: '상세' }));
    expect([fold.open, kept.open, note.open]).toEqual([true, true, true]);
    fireEvent.click(screen.getByRole('radio', { name: '요약' }));
    expect([fold.open, kept.open, note.open]).toEqual([false, true, false]);
  });
});
