import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { applyUiPrefs, DEFAULT_UI_PREFS, normalizeUiPrefs, readUiPrefs, saveUiPrefs, type UiPrefs } from '../lib/uiPrefs';

interface UiPrefsValue { prefs: UiPrefs; setPrefs: (patch: Partial<UiPrefs>) => void; resetPrefs: () => void }

/** 공급자 없이 쓰이면(부품 시험 등) 기본 화면 그대로 동작한다. */
const UiPrefsContext = createContext<UiPrefsValue>({ prefs: DEFAULT_UI_PREFS, setPrefs: () => undefined, resetPrefs: () => undefined });

/** 화면 설정을 앱 전체에 나눠 준다. 바뀌면 바로 <html> 속성에 적용하고 이 브라우저에 저장한다. */
export function UiPrefsProvider({ children, initial }: { children: ReactNode; initial?: UiPrefs }) {
  const [prefs, setState] = useState<UiPrefs>(() => initial ?? readUiPrefs());
  useEffect(() => { applyUiPrefs(prefs); saveUiPrefs(prefs); }, [prefs]);
  const setPrefs = useCallback((patch: Partial<UiPrefs>) => setState((current) => normalizeUiPrefs({ ...current, ...patch }, current)), []);
  const resetPrefs = useCallback(() => setState(DEFAULT_UI_PREFS), []);
  const value = useMemo(() => ({ prefs, setPrefs, resetPrefs }), [prefs, setPrefs, resetPrefs]);
  return <UiPrefsContext.Provider value={value}>{children}</UiPrefsContext.Provider>;
}

export function useUiPrefs(): UiPrefsValue {
  return useContext(UiPrefsContext);
}
