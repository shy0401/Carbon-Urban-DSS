import { Activity, BarChart3, BookOpen, BrainCircuit, Database, FileText, Globe2, LandPlot, Leaf, Map, Menu, PlayCircle, X } from 'lucide-react';
import { useEffect, useRef, useState, type RefObject } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { useSystemInfo } from '../hooks/useSystemInfo';
import { AnalysisScopeBar } from './AnalysisScopeBar';
import { LinkedRegionNotice } from './LinkedRegionNotice';
import { RegionOpenNotice } from './RegionOpenNotice';
import { SystemStatus } from './SystemStatus';
import { TitleBlock } from './TitleBlock';

/** 메뉴 이름은 사용설명서·안내 영상과 같게 둔다. 묶음 제목(탐색·계획·결과·도움)은 길잡이일 뿐 주소나 이름을 바꾸지 않는다. */
const navigation = [
  { group: '탐색', items: [
    { to: '/regions', label: '전국 지역', icon: Globe2 },
    { to: '/', label: '대시보드', icon: BarChart3, end: true },
    { to: '/map', label: '지도 분석', icon: Map },
    { to: '/analysis', label: '분석', icon: Activity },
  ] },
  { group: '계획', items: [
    { to: '/model', label: '모델', icon: BrainCircuit },
    { to: '/area', label: '지역 시뮬레이션', icon: LandPlot },
    { to: '/simulation', label: '시뮬레이션', icon: PlayCircle },
  ] },
  { group: '결과', items: [
    { to: '/data', label: '수집 데이터', icon: Database },
    { to: '/reports', label: '검토 보고서', icon: FileText },
  ] },
  { group: '도움', items: [
    { to: '/guide', label: '사용 방법', icon: BookOpen },
  ] },
];

/**
 * 가로·세로로 넘쳐 스크롤되는 표·코드 상자는 키보드로도 움직일 수 있어야 한다(WCAG 2.1.1, axe scrollable-region-focusable).
 * 화면마다 손대지 않고, 본문이 바뀔 때마다 실제로 넘치는 상자에만 tabindex=0을 준다.
 */
function useScrollableRegions(main: RefObject<HTMLElement | null>) {
  useEffect(() => {
    const root = main.current;
    if (!root || typeof MutationObserver === 'undefined') return undefined;
    const mark = () => {
      for (const el of root.querySelectorAll<HTMLElement>('.table-wrap, pre, .guide-metrics')) {
        const scrolls = el.scrollWidth > el.clientWidth + 1 || el.scrollHeight > el.clientHeight + 1;
        if (scrolls && !el.hasAttribute('tabindex')) { el.setAttribute('tabindex', '0'); el.dataset.scrollFocus = '1'; }
        else if (!scrolls && el.dataset.scrollFocus) { el.removeAttribute('tabindex'); delete el.dataset.scrollFocus; }
      }
    };
    let timer = 0;
    const schedule = () => { window.clearTimeout(timer); timer = window.setTimeout(mark, 150); };
    const observer = new MutationObserver(schedule);
    observer.observe(root, { childList: true, subtree: true });
    window.addEventListener('resize', schedule);
    schedule();
    return () => { observer.disconnect(); window.removeEventListener('resize', schedule); window.clearTimeout(timer); };
  }, [main]);
}

/** 데스크톱에서 본문을 내려 읽는 동안 고정 머리를 한 줄 요약으로 줄인다(히스테리시스: 160px 넘게 내리면 줄이고 40px 안으로 올리면 되돌림). */
function useCompactHeader(): boolean {
  const [compact, setCompact] = useState(false);
  useEffect(() => {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return undefined;
    const wide = window.matchMedia('(min-width: 1024px)');
    let current = false;
    const update = () => {
      const y = window.scrollY || 0;
      const next = wide.matches && (current ? y > 40 : y > 160);
      if (next !== current) { current = next; setCompact(next); }
    };
    window.addEventListener('scroll', update, { passive: true });
    wide.addEventListener?.('change', update);
    update();
    return () => { window.removeEventListener('scroll', update); wide.removeEventListener?.('change', update); };
  }, []);
  return compact;
}

/** 앱 셸 (DESIGN.md 4.1): 220px 먹녹색 사이드바 + 표제란 머리. 1023px 이하에서는 드로어. */
export function Layout() {
  const [open, setOpen] = useState(false);
  const compact = useCompactHeader();
  const system = useSystemInfo();
  const regionName = system?.region?.short_name ?? '전주시';
  // 고정 머리의 실제 높이를 --shell-header-h로 알려 아래에 붙는 막대(지역 시뮬 요약)가 머리 뒤에 숨지 않게 한다(사용성 검토 F5)
  const header = useRef<HTMLElement>(null);
  const main = useRef<HTMLElement>(null);
  useScrollableRegions(main);
  useEffect(() => {
    const el = header.current;
    if (!el || typeof ResizeObserver === 'undefined') return undefined;
    const set = () => document.documentElement.style.setProperty('--shell-header-h', `${Math.ceil(el.getBoundingClientRect().height)}px`);
    set();
    const observer = new ResizeObserver(set);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  return <div className="app-shell">
    <a className="skip-link" href="#main-content">본문으로 건너뛰기</a>
    <aside className={`sidebar${open ? ' open' : ''}`}>
      <div className="brand"><span className="brand-mark" aria-hidden="true"><Leaf size={17} /></span><span><strong>Carbon Urban DSS</strong><small>{regionName} · 전국 도시 탄소 의사결정 지원</small></span></div>
      <button className="mobile-close" aria-label="메뉴 닫기" onClick={() => setOpen(false)}><X size={20} /></button>
      <nav aria-label="주요 메뉴">
        {navigation.map(({ group, items }) => <div key={group} className="nav-group" role="group" aria-label={group}>
          <span className="nav-group-label" aria-hidden="true">{group}</span>
          {items.map(({ to, label, icon: Icon, end }) => <NavLink key={to} to={to} end={end} onClick={() => setOpen(false)}><Icon size={18} aria-hidden="true" /><span>{label}</span></NavLink>)}
        </div>)}
      </nav>
      <SystemStatus />
    </aside>
    {open && <button className="backdrop" aria-label="메뉴 닫기" onClick={() => setOpen(false)} />}
    <main className="main-shell" id="main-content" tabIndex={-1} ref={main}>
      <header className={`shell-header${compact ? ' compact' : ''}`} ref={header}>
        <div className="mobile-top"><button className="menu-button" aria-label="메뉴 열기" onClick={() => setOpen(true)}><Menu size={20} /></button><strong>Carbon Urban DSS</strong></div>
        <div className="shell-scope"><TitleBlock /><AnalysisScopeBar /></div>
      </header>
      <RegionOpenNotice />
      <LinkedRegionNotice />
      <Outlet />
    </main>
  </div>;
}
