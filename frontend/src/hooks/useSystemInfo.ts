import { useEffect, useSyncExternalStore } from 'react';
import { api } from '../lib/api';
import { useAnalysisScope } from './useAnalysisScope';

export interface PreparedRegion { code: string; name: string; short_name: string; status: string; grid_count: number; default_grid_id: string | null; level?: 'DETAILED' | 'BASIC' | 'NONE' }
export interface SystemInfo {
  offline_mode: boolean; baseline_year: number; version: string;
  /** Grid of the default 대상지 of the current region. */
  default_grid_id?: string | null;
  default_region?: string;
  region?: { code: string; name: string; short_name: string; center: [number, number] | null };
  /** Study regions that have analysis grids. */
  regions?: PreparedRegion[];
}

// One shared /api/system read for the sidebar mode switch, the title block and the region selector.
let info: SystemInfo | null = null;
let requested: string | null | undefined;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((fn) => fn());

export function setSystemInfo(next: SystemInfo | null) { info = next; emit(); }

export function refreshSystemInfo(region: string | null = requested ?? null) {
  requested = region;
  const query = region ? `?region=${encodeURIComponent(region)}` : '';
  return api<SystemInfo>(`/system${query}`).then((value) => { if (value && typeof value.offline_mode === 'boolean' && value.version) setSystemInfo(value); }).catch(() => undefined);
}

let watching = false;
function subscribe(fn: () => void) {
  listeners.add(fn);
  if (!watching && typeof window !== 'undefined') {
    watching = true;
    window.addEventListener('carbon-system-change', () => void refreshSystemInfo());
    window.addEventListener('carbon-regions-change', () => void refreshSystemInfo());
  }
  return () => { listeners.delete(fn); };
}

export function useSystemInfo() {
  const { region } = useAnalysisScope();
  useEffect(() => { if (requested === undefined || requested !== region) void refreshSystemInfo(region); }, [region]);
  return useSyncExternalStore(subscribe, () => info, () => info);
}
