import { Cloud, HardDrive } from 'lucide-react';
import { useEffect, useState } from 'react';
import { api } from '../lib/api';

interface SystemInfo { offline_mode: boolean; baseline_year: number; version: string; }

export function SystemStatus() {
  const [system, setSystem] = useState<SystemInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const [error,setError]=useState<string|null>(null);
  useEffect(() => { api<SystemInfo>('/system').then((value) => value.version && setSystem(value)).catch(() => undefined); }, []);
  if (!system) return null;
  const toggle = async () => { setBusy(true);setError(null); try { const next = await api<SystemInfo>('/system/offline', { method: 'POST', body: JSON.stringify({ enabled: !system.offline_mode }) }); setSystem(next);window.dispatchEvent(new Event('carbon-system-change')); } catch(e){setError(e instanceof Error?e.message:'전환 실패');} finally { setBusy(false); } };
  return <><button className={`system-status ${system.offline_mode ? 'offline' : ''}`} onClick={() => void toggle()} disabled={busy} title="데모 외부 API 접근 모드 전환">{system.offline_mode ? <HardDrive size={14} /> : <Cloud size={14} />}<span><strong>{system.offline_mode ? '오프라인 데모' : '온라인 수집'}</strong><small>{system.offline_mode ? '검증된 로컬 스냅샷' : `기준 ${system.baseline_year}`}</small></span></button>{error&&<p role="alert" className="inline-error">{error}</p>}</>;
}
