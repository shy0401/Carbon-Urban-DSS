import { useSyncExternalStore } from 'react';
import { api } from '../lib/api';

export interface SystemInfo { offline_mode: boolean; baseline_year: number; version: string; /** Grid of the default 대상지 (testbed sector). */ default_grid_id?: string | null }

// One shared /api/system read for the sidebar mode switch and the title block.
let info: SystemInfo | null = null;
let requested = false;
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((fn) => fn());

export function setSystemInfo(next: SystemInfo | null) { info = next; emit(); }

export function refreshSystemInfo() {
  requested = true;
  return api<SystemInfo>('/system').then((value) => { if (value && typeof value.offline_mode === 'boolean' && value.version) setSystemInfo(value); }).catch(() => undefined);
}

let watching = false;
function subscribe(fn: () => void) {
  listeners.add(fn);
  if (!requested) void refreshSystemInfo();
  if (!watching && typeof window !== 'undefined') { watching = true; window.addEventListener('carbon-system-change', () => void refreshSystemInfo()); }
  return () => { listeners.delete(fn); };
}

export function useSystemInfo() { return useSyncExternalStore(subscribe, () => info, () => info); }
