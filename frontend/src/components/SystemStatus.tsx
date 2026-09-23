import { Cloud, HardDrive } from 'lucide-react';
import { useState } from 'react';
import { setSystemInfo, useSystemInfo, type SystemInfo } from '../hooks/useSystemInfo';
import { api } from '../lib/api';

/** 사이드바 하단: 온라인/오프라인 칩(누르면 전환)과 버전. */
export function SystemStatus() {
  const system = useSystemInfo();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!system) return null;
  const toggle = async () => {
    setBusy(true); setError(null);
    try { const next = await api<SystemInfo>('/system/offline', { method: 'POST', body: JSON.stringify({ enabled: !system.offline_mode }) }); setSystemInfo(next); window.dispatchEvent(new Event('carbon-system-change')); }
    catch (e) { setError(e instanceof Error ? e.message : '전환 실패'); }
    finally { setBusy(false); }
  };
  return <div className="sidebar-foot">
    <button className={`system-status${system.offline_mode ? ' offline' : ''}`} onClick={() => void toggle()} disabled={busy} aria-label={`${system.offline_mode ? '오프라인 데모' : '온라인 수집'} 모드, 눌러서 전환`}>
      {system.offline_mode ? <HardDrive size={14} aria-hidden="true" /> : <Cloud size={14} aria-hidden="true" />}
      <span><strong>{system.offline_mode ? '오프라인 데모' : '온라인 수집'}</strong><small>{system.offline_mode ? '검증된 로컬 스냅샷' : '외부 API 수집 가능'}</small></span>
    </button>
    {error && <p role="alert" className="sidebar-error">{error}</p>}
    <p className="sidebar-version">버전 {system.version}<br />기준연도 {system.baseline_year}</p>
  </div>;
}
