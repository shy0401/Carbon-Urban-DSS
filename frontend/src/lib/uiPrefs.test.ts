import { afterEach, describe, expect, it } from 'vitest';
import { applyUiPrefs, DEFAULT_UI_PREFS, normalizeUiPrefs, readUiPrefs, saveUiPrefs, UI_PREFS_STORAGE_KEY } from './uiPrefs';

describe('uiPrefs (화면 설정)', () => {
  afterEach(() => { window.localStorage.clear(); for (const key of ['uiMode', 'theme', 'accent']) delete document.documentElement.dataset[key]; document.documentElement.style.colorScheme = ''; });

  it('저장된 값이 없으면 기본 화면(요약·밝게·녹색)이다', () => {
    expect(readUiPrefs('')).toEqual(DEFAULT_UI_PREFS);
    expect(DEFAULT_UI_PREFS).toEqual({ mode: 'brief', theme: 'light', accent: 'green' });
  });

  it('모르는 값은 버리고 알던 값을 남긴다', () => {
    expect(normalizeUiPrefs({ mode: 'kiosk', theme: 'dark', accent: 7 })).toEqual({ mode: 'brief', theme: 'dark', accent: 'green' });
    expect(normalizeUiPrefs('깨진 값', { mode: 'detail', theme: 'dark', accent: 'ink' })).toEqual({ mode: 'detail', theme: 'dark', accent: 'ink' });
  });

  it('저장한 값을 다시 읽고, 주소의 ?ui= · ?theme= · ?accent= 가 저장된 값보다 먼저다', () => {
    saveUiPrefs({ mode: 'detail', theme: 'dark', accent: 'navy' });
    expect(readUiPrefs('')).toEqual({ mode: 'detail', theme: 'dark', accent: 'navy' });
    expect(readUiPrefs('?ui=present&region=52110')).toEqual({ mode: 'present', theme: 'dark', accent: 'navy' });
    expect(readUiPrefs('?ui=nope&theme=light&accent=ink')).toEqual({ mode: 'detail', theme: 'light', accent: 'ink' });
  });

  it('저장소의 값이 JSON이 아니어도 기본값으로 연다', () => {
    window.localStorage.setItem(UI_PREFS_STORAGE_KEY, '{');
    expect(readUiPrefs('')).toEqual(DEFAULT_UI_PREFS);
  });

  it('고른 값을 <html> 속성으로 적는다(기본값도 적는다)', () => {
    applyUiPrefs({ mode: 'present', theme: 'dark', accent: 'navy' });
    expect(document.documentElement.dataset).toMatchObject({ uiMode: 'present', theme: 'dark', accent: 'navy' });
    expect(document.documentElement.style.colorScheme).toBe('dark');
    applyUiPrefs(DEFAULT_UI_PREFS);
    expect(document.documentElement.dataset).toMatchObject({ uiMode: 'brief', theme: 'light', accent: 'green' });
  });
});
