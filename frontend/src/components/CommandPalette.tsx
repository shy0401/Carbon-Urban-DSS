import { Search } from 'lucide-react';
import { Fragment, useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from 'react';
import { useNavigate } from 'react-router-dom';
import { useUiPrefs } from '../hooks/useUiPrefs';
import { UI_ACCENTS, UI_MODES, UI_THEMES } from '../lib/uiPrefs';
import { FLOW_STEPS } from './FlowBar';

interface Command { id: string; group: string; label: string; hint?: string; keywords?: string; run: () => void }

/** 화면 이름은 왼쪽 메뉴와 같다. keywords는 찾기에만 쓰는 다른 말. */
const PAGES: Array<{ to: string; label: string; hint: string; keywords: string }> = [
  { to: '/', label: '대시보드', hint: '핵심 지표', keywords: '현황 홈 dashboard' },
  { to: '/map', label: '지도 분석', hint: '격자·행정동 지도', keywords: '지역별 격자 map' },
  { to: '/analysis', label: '분석', hint: '월별·공식 통계', keywords: '추이 analysis' },
  { to: '/area', label: '지역 시뮬레이션', hint: '개발 전후', keywords: '개발 전후 구역 area' },
  { to: '/simulation', label: '시뮬레이션', hint: '계획안 계산', keywords: '계획 3D simulation' },
  { to: '/reports', label: '검토 보고서', hint: '감축 방안', keywords: '보고서 감축 사다리 report' },
  { to: '/regions', label: '전국 지역', hint: '시·군·구 준비', keywords: '전국 regions' },
  { to: '/data', label: '수집 데이터', hint: '출처와 수집 상태', keywords: '자료 출처 data' },
  { to: '/model', label: '모델', hint: '검증과 신뢰도', keywords: '검증 신뢰도 보정 model' },
  { to: '/guide', label: '사용 방법', hint: '화면 읽는 법', keywords: '도움 설명서 guide' },
];

/**
 * 빠른 이동 (Ctrl+K, DESIGN.md 4.7): 화면 이름이나 설정을 몇 글자로 찾아 바로 간다.
 * 글자를 치면 줄어들고, ↑↓로 고르고 Enter로 실행, Esc로 닫는다.
 */
export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const navigate = useNavigate();
  const { prefs, setPrefs } = useUiPrefs();
  const [query, setQuery] = useState('');
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);
  const returnTo = useRef<Element | null>(null);

  const commands = useMemo<Command[]>(() => [
    ...PAGES.map((page) => ({ id: `go:${page.to}`, group: '화면', label: page.label, hint: page.hint, keywords: page.keywords, run: () => navigate(page.to) })),
    ...FLOW_STEPS.map((step, i) => ({ id: `flow:${step.key}`, group: '보는 순서', label: `${i + 1}단계 ${step.label}`, hint: step.question, keywords: '순서 단계 발표', run: () => navigate(step.stops[0]) })),
    ...UI_MODES.map((option) => ({ id: `mode:${option.value}`, group: '화면 설정', label: `보기 방식: ${option.label}`, hint: option.value === prefs.mode ? '지금 설정' : undefined, keywords: '모드 발표 요약 상세', run: () => setPrefs({ mode: option.value }) })),
    ...UI_THEMES.map((option) => ({ id: `theme:${option.value}`, group: '화면 설정', label: `색 테마: ${option.label}`, hint: option.value === prefs.theme ? '지금 설정' : undefined, keywords: '테마 다크 라이트 어둡게 밝게', run: () => setPrefs({ theme: option.value }) })),
    ...UI_ACCENTS.map((option) => ({ id: `accent:${option.value}`, group: '화면 설정', label: `강조색: ${option.label}`, hint: option.value === prefs.accent ? '지금 설정' : undefined, keywords: '색 강조', run: () => setPrefs({ accent: option.value }) })),
  ], [navigate, prefs, setPrefs]);

  const shown = useMemo(() => {
    const words = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
    if (!words.length) return commands;
    return commands.filter((command) => { const text = `${command.label} ${command.group} ${command.hint ?? ''} ${command.keywords ?? ''}`.toLowerCase(); return words.every((word) => text.includes(word)); });
  }, [commands, query]);

  useEffect(() => {
    if (!open) return undefined;
    returnTo.current = document.activeElement;
    setQuery(''); setActive(0);
    const timer = window.setTimeout(() => input.current?.focus(), 0);
    return () => { window.clearTimeout(timer); if (returnTo.current instanceof HTMLElement) returnTo.current.focus(); };
  }, [open]);
  useEffect(() => { setActive(0); }, [query]);

  if (!open) return null;
  const run = (command: Command | undefined) => { if (!command) return; onClose(); command.run(); };
  const onKeyDown = (event: ReactKeyboardEvent) => {
    if (event.key === 'ArrowDown') { event.preventDefault(); setActive((i) => (shown.length ? (i + 1) % shown.length : 0)); }
    else if (event.key === 'ArrowUp') { event.preventDefault(); setActive((i) => (shown.length ? (i - 1 + shown.length) % shown.length : 0)); }
    else if (event.key === 'Enter') { event.preventDefault(); run(shown[active]); }
    else if (event.key === 'Escape') { event.preventDefault(); onClose(); }
  };
  let lastGroup = '';
  return <div className="command-scrim" onPointerDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
    <div className="command-palette" role="dialog" aria-modal="true" aria-label="빠른 이동" data-testid="command-palette" onKeyDown={onKeyDown}>
      <div className="command-input"><Search size={16} aria-hidden="true" />
        <input ref={input} type="text" role="combobox" aria-expanded="true" aria-controls="command-list" aria-activedescendant={shown[active] ? `command-${shown[active].id}` : undefined} aria-label="화면이나 설정 찾기" placeholder="화면이나 설정을 찾습니다 (예: 보고서, 발표, 어둡게)" value={query} onChange={(event) => setQuery(event.target.value)} autoComplete="off" spellCheck={false} />
        <kbd>Esc</kbd>
      </div>
      <ul className="command-list" id="command-list" role="listbox" aria-label="찾은 항목">
        {shown.map((command, i) => {
          const head = command.group !== lastGroup ? command.group : null;
          lastGroup = command.group;
          return <Fragment key={command.id}>
            {head && <li className="command-group" role="presentation">{head}</li>}
            <li id={`command-${command.id}`} role="option" aria-selected={i === active} className={i === active ? 'active' : undefined} onPointerMove={() => setActive(i)} onClick={() => run(command)}>
              <span className="command-label">{command.label}</span>{command.hint && <span className="command-hint">{command.hint}</span>}
            </li>
          </Fragment>;
        })}
        {!shown.length && <li className="command-empty" role="presentation">찾는 항목이 없습니다. 화면 이름(예: 지도, 보고서)이나 설정(예: 발표)을 쳐 보세요.</li>}
      </ul>
    </div>
  </div>;
}
