import { Activity, BarChart3, BookOpen, BrainCircuit, Database, FileText, Globe2, LandPlot, Leaf, Map, Menu, PlayCircle, X } from 'lucide-react';
import { useState } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { useSystemInfo } from '../hooks/useSystemInfo';
import { AnalysisScopeBar } from './AnalysisScopeBar';
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
  return <div className="app-shell">
    <aside className={`sidebar${open ? ' open' : ''}`}>
      <div className="brand"><span className="brand-mark" aria-hidden="true"><Leaf size={17} /></span><span><strong>Carbon Urban DSS</strong><small>{regionName} · 전국 도시 탄소 의사결정 지원</small></span></div>
      <button className="mobile-close" aria-label="메뉴 닫기" onClick={() => setOpen(false)}><X size={20} /></button>
      <nav aria-label="주요 메뉴">
        {navigation.map(({ to, label, icon: Icon, end }) => <NavLink key={to} to={to} end={end} onClick={() => setOpen(false)}><Icon size={18} aria-hidden="true" /><span>{label}</span></NavLink>)}
      </nav>
      <SystemStatus />
    </aside>
    {open && <button className="backdrop" aria-label="메뉴 닫기" onClick={() => setOpen(false)} />}
    <main className="main-shell">
      <header className="shell-header">
        <div className="mobile-top"><button className="menu-button" aria-label="메뉴 열기" onClick={() => setOpen(true)}><Menu size={20} /></button><strong>Carbon Urban DSS</strong></div>
        <div className="shell-scope"><TitleBlock /><AnalysisScopeBar /></div>
      </header>
      <Outlet />
    </main>
  </div>;
}
