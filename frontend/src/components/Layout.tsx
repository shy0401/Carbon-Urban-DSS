import { Activity, BarChart3, BrainCircuit, Building2, Database, Leaf, Map, Menu, PlayCircle, X } from 'lucide-react';
import { useState } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import { SystemStatus } from './SystemStatus';
import { AnalysisScopeBar } from './AnalysisScopeBar';

const navigation = [
  { to: '/', label: '대시보드', icon: BarChart3, end: true },
  { to: '/map', label: '지도 분석', icon: Map },
  { to: '/analysis', label: '분석', icon: Activity },
  { to: '/model', label: '모델', icon: BrainCircuit },
  { to: '/simulation', label: '시뮬레이션', icon: PlayCircle },
  { to: '/data', label: '수집 데이터', icon: Database },
  { to: '/reports', label: '검토 보고서', icon: BarChart3 },
];

export function Layout() {
  const [open, setOpen] = useState(false);
  return <div className="app-shell">
    <aside className={`sidebar ${open ? 'open' : ''}`}>
      <div className="brand"><span className="brand-mark"><Leaf size={22} /></span><span><strong>Carbon Urban</strong><small>Decision Support System</small></span></div>
      <button className="mobile-close" aria-label="메뉴 닫기" onClick={() => setOpen(false)}><X /></button>
      <div className="side-context"><Building2 size={16} /><span><small>분석 대상</small><strong>전주시 도시 탄소</strong></span></div>
      <nav aria-label="주요 메뉴">
        {navigation.map(({ to, label, icon: Icon, end }) => <NavLink key={to} to={to} end={end} onClick={() => setOpen(false)}><Icon size={18} /><span>{label}</span></NavLink>)}
      </nav>
      <SystemStatus />
      <div className="sidebar-foot"><span className="live-dot" /><span><strong>출처 추적 활성</strong><small>API·로컬 DB 응답 기준</small></span></div>
    </aside>
    {open && <button className="backdrop" aria-label="메뉴 닫기" onClick={() => setOpen(false)} />}
    <main className="main-shell">
      <div className="mobile-top"><button aria-label="메뉴 열기" onClick={() => setOpen(true)}><Menu /></button><strong>Carbon Urban DSS</strong></div>
      <AnalysisScopeBar /><Outlet />
    </main>
  </div>;
}
