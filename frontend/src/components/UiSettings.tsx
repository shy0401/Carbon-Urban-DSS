import { SlidersHorizontal } from 'lucide-react';
import { useEffect, useId, useRef, useState } from 'react';
import { useUiPrefs } from '../hooks/useUiPrefs';
import { UI_ACCENTS, UI_MODES, UI_THEMES } from '../lib/uiPrefs';

/** 한 줄 선택 단추(라디오 묶음). 화살표 키로 옮기고, 고르는 즉시 화면에 적용된다. */
function Segmented<T extends string>({ legend, value, options, onChange, swatch = false }: {
  legend: string; value: T; options: ReadonlyArray<{ value: T; label: string }>; onChange: (value: T) => void; swatch?: boolean;
}) {
  const name = useId();
  return <fieldset className="segmented">
    <legend>{legend}</legend>
    <div className="segmented-row">
      {options.map((option) => <label key={option.value} className={option.value === value ? 'on' : undefined}>
        <input type="radio" name={name} value={option.value} checked={option.value === value} onChange={() => onChange(option.value)} />
        {swatch && <i className={`accent-dot accent-${option.value}`} aria-hidden="true" />}
        <span>{option.label}</span>
      </label>)}
    </div>
  </fieldset>;
}

/**
 * 화면 설정 (DESIGN.md 4.7): 보기 방식(요약·발표·상세) · 색 테마 · 강조색을 사이트에서 바로 바꾼다.
 * 값·계산은 바뀌지 않고, 고른 설정은 이 브라우저에 남는다.
 */
export function UiSettings() {
  const { prefs, setPrefs, resetPrefs } = useUiPrefs();
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!open) return undefined;
    const outside = (event: PointerEvent) => { if (wrap.current && !wrap.current.contains(event.target as Node)) setOpen(false); };
    const escape = (event: KeyboardEvent) => { if (event.key === 'Escape') { setOpen(false); button.current?.focus(); } };
    document.addEventListener('pointerdown', outside);
    document.addEventListener('keydown', escape);
    return () => { document.removeEventListener('pointerdown', outside); document.removeEventListener('keydown', escape); };
  }, [open]);
  const mode = UI_MODES.find((option) => option.value === prefs.mode) ?? UI_MODES[0];
  return <div className="ui-settings" ref={wrap}>
    <button ref={button} type="button" className="tool-button" aria-label="화면 설정" aria-haspopup="dialog" aria-expanded={open} aria-controls="ui-settings-panel" data-testid="ui-settings-button" onClick={() => setOpen(!open)}>
      <SlidersHorizontal size={16} aria-hidden="true" /><span>화면 설정</span>
    </button>
    {open && <div className="ui-settings-panel" id="ui-settings-panel" role="dialog" aria-label="화면 설정" data-testid="ui-settings-panel">
      <Segmented legend="보기 방식" value={prefs.mode} options={UI_MODES} onChange={(value) => setPrefs({ mode: value })} />
      <p className="ui-settings-hint" role="status">{mode.hint}</p>
      <Segmented legend="색 테마" value={prefs.theme} options={UI_THEMES} onChange={(value) => setPrefs({ theme: value })} />
      <Segmented legend="강조색" value={prefs.accent} options={UI_ACCENTS} onChange={(value) => setPrefs({ accent: value })} swatch />
      <p className="ui-settings-foot">고르면 바로 바뀌고 이 브라우저에 저장됩니다. 값과 계산은 바뀌지 않습니다. <button type="button" className="link-button" onClick={resetPrefs}>처음 설정으로</button></p>
    </div>}
  </div>;
}
