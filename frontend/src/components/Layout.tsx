import { Activity, BarChart3, BookOpen, BrainCircuit, Database, FileText, Globe2, LandPlot, Leaf, Map, Menu, PlayCircle, X } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { useSystemInfo } from '../hooks/useSystemInfo';
import { AnalysisScopeBar } from './AnalysisScopeBar';
import { LinkedRegionNotice } from './LinkedRegionNotice';
import { RegionOpenNotice } from './RegionOpenNotice';
import { SystemStatus } from './SystemStatus';
import { TitleBlock } from './TitleBlock';

const navigation = [
  { to: '/regions', label: '전국 지역', icon: Globe2 },
  { to: '/', label: '대시보드', icon: BarChart3, end: true },
  { to: '/map', label: '지도 분석', icon: Map },
  { to: '/analysis', label: '분석', icon: Activity },
  { to: '/model', label: '모델', icon: BrainCircuit },
  { to: '/area', label: '지역 시뮬레이션', icon: LandPlot },
  { to: '/simulation', label: '시뮬레이션', icon: PlayCircle },
  { to: '/data', label: '수집 데이터', icon: Database },
  { to: '/reports', label: '검토 보고서', icon: FileText },
  { to: '/guide', label: '사용 방법', icon: BookOpen },
];

/** 앱 셸 (DESIGN.md 4.1): 220px 먹녹색 사이드바 + 표제란 머리. 1023px 이하에서는 드로어. */
export function Layout() {
  const [open, setOpen] = useState(false);
  const system = useSystemInfo();
  const regionName = system?.region?.short_name ?? '전주시';
  // 고정 머리의 실제 높이를 --shell-header-h로 알려 아래에 붙는 막대(지역 시뮬 요약)가 머리 뒤에 숨지 않게 한다(사용성 검토 F5)
  const header = useRef<HTMLElement>(null);
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
        {navigation.map(({ to, label, icon: Icon, end }) => <NavLink key={to} to={to} end={end} onClick={() => setOpen(false)}><Icon size={18} aria-hidden="true" /><span>{label}</span></NavLink>)}
      </nav>
      <SystemStatus />
    </aside>
    {open && <button className="backdrop" aria-label="메뉴 닫기" onClick={() => setOpen(false)} />}
    <main className="main-shell" id="main-content" tabIndex={-1}>
      <header className="shell-header" ref={header}>
        <div className="mobile-top"><button className="menu-button" aria-label="메뉴 열기" onClick={() => setOpen(true)}><Menu size={20} /></button><strong>Carbon Urban DSS</strong></div>
        <div className="shell-scope"><TitleBlock /><AnalysisScopeBar /></div>
      </header>
      <RegionOpenNotice />
      <LinkedRegionNotice />
      <Outlet />
    </main>
  </div>;
}
