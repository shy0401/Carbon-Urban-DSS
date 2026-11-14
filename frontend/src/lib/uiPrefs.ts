/**
 * 화면 설정 (DESIGN.md 4.7): 사이트에서 바로 바꾸는 보기 방식 · 색 테마 · 강조색.
 * 고른 값은 <html>의 data-* 속성으로만 전달되고(styles/themes.css가 읽음), 계산 값·자료는 바꾸지 않는다.
 * 주소의 ?ui=present&theme=dark&accent=navy 로도 정할 수 있다(발표용 링크). 주소 값이 저장된 값보다 먼저다.
 */
export type UiMode = 'brief' | 'present' | 'detail';
export type UiTheme = 'light' | 'dark';
export type UiAccent = 'green' | 'navy' | 'ink';
export interface UiPrefs { mode: UiMode; theme: UiTheme; accent: UiAccent }

export const DEFAULT_UI_PREFS: UiPrefs = { mode: 'brief', theme: 'light', accent: 'green' };

export const UI_MODES: ReadonlyArray<{ value: UiMode; label: string; hint: string }> = [
  { value: 'brief', label: '요약', hint: '핵심 수치와 그림 하나만 먼저 보이고, 근거는 접어 둡니다.' },
  { value: 'present', label: '발표', hint: '글자를 키우고 왼쪽 메뉴와 설명을 숨깁니다. 위의 보는 순서로 넘깁니다.' },
  { value: 'detail', label: '상세', hint: '접어 둔 근거·표·설명을 모두 펼쳐 보여 줍니다.' },
];
export const UI_THEMES: ReadonlyArray<{ value: UiTheme; label: string }> = [
  { value: 'light', label: '밝게' },
  { value: 'dark', label: '어둡게' },
];
export const UI_ACCENTS: ReadonlyArray<{ value: UiAccent; label: string }> = [
  { value: 'green', label: '녹색' },
  { value: 'navy', label: '남색' },
  { value: 'ink', label: '먹색' },
];

export const UI_PREFS_STORAGE_KEY = 'carbon-dss-ui';

function pick<T extends string>(value: unknown, allowed: ReadonlyArray<{ value: T }>, fallback: T): T {
  return typeof value === 'string' && allowed.some((option) => option.value === value) ? (value as T) : fallback;
}

/** 모르는 값은 버리고 base의 값을 남긴다(저장된 값이 옛 형식이어도 화면이 깨지지 않게). */
export function normalizeUiPrefs(raw: unknown, base: UiPrefs = DEFAULT_UI_PREFS): UiPrefs {
  const source = raw && typeof raw === 'object' ? (raw as Record<string, unknown>) : {};
  return {
    mode: pick(source.mode, UI_MODES, base.mode),
    theme: pick(source.theme, UI_THEMES, base.theme),
    accent: pick(source.accent, UI_ACCENTS, base.accent),
  };
}

/** 저장된 값 위에 주소의 ?ui= · ?theme= · ?accent= 를 덮어 읽는다. 저장소를 못 쓰는 브라우저에서는 기본값. */
export function readUiPrefs(search?: string): UiPrefs {
  let stored: unknown = null;
  try { stored = JSON.parse(window.localStorage.getItem(UI_PREFS_STORAGE_KEY) ?? 'null'); } catch { stored = null; }
  const base = normalizeUiPrefs(stored);
  let params: URLSearchParams;
  try { params = new URLSearchParams(search ?? window.location.search); } catch { return base; }
  return normalizeUiPrefs({ mode: params.get('ui') ?? undefined, theme: params.get('theme') ?? undefined, accent: params.get('accent') ?? undefined }, base);
}

export function saveUiPrefs(prefs: UiPrefs): void {
  try { window.localStorage.setItem(UI_PREFS_STORAGE_KEY, JSON.stringify(prefs)); } catch { /* 저장하지 못해도 이번 화면에는 적용된다 */ }
}

/** <html data-ui-mode data-theme data-accent>. 기본값일 때도 속성을 적어 CSS 선택자가 한 가지 모양이 되게 한다. */
export function applyUiPrefs(prefs: UiPrefs, root: HTMLElement | null = typeof document === 'undefined' ? null : document.documentElement): void {
  if (!root) return;
  root.dataset.uiMode = prefs.mode;
  root.dataset.theme = prefs.theme;
  root.dataset.accent = prefs.accent;
  root.style.colorScheme = prefs.theme;
}
