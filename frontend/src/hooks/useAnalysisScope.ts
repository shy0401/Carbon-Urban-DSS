import { useSyncExternalStore } from 'react';

/** 분석 범위: 연도, 분석 지역(법정 시·군·구 코드, null = 최초 연구 지역 전주시), 선택 격자. */
type Scope = { year: number; gridId: string | null; region: string | null };
let scope: Scope = { year: 2025, gridId: null, region: null };
try {
  const saved = JSON.parse(localStorage.getItem('carbon-analysis-scope') || 'null');
  if (saved && Number.isInteger(saved.year) && saved.year >= 2000 && saved.year <= 2100) {
    scope = {
      year: saved.year,
      gridId: typeof saved.gridId === 'string' ? saved.gridId : null,
      region: typeof saved.region === 'string' && /^\d{5}$/.test(saved.region) ? saved.region : null,
    };
  }
} catch { /* Optional browser storage. */ }
const listeners = new Set<() => void>();

export function setAnalysisScope(next: Partial<Scope>) {
  // A grid belongs to one region: switching the region clears the selected grid.
  const regionChanged = next.region !== undefined && next.region !== scope.region;
  scope = { ...scope, ...next, ...(regionChanged && next.gridId === undefined ? { gridId: null } : {}) };
  try { localStorage.setItem('carbon-analysis-scope', JSON.stringify(scope)); } catch { /* Private mode still works in memory. */ }
  listeners.forEach((fn) => fn());
}

/** `region=…` query part (empty for the original region). */
export function regionParam(region: string | null, prefix = '&') { return region ? `${prefix}region=${encodeURIComponent(region)}` : ''; }

export function useAnalysisScope() {
  const current = useSyncExternalStore((fn) => { listeners.add(fn); return () => listeners.delete(fn); }, () => scope);
  const query = `year=${current.year}${current.gridId ? `&grid_id=${encodeURIComponent(current.gridId)}` : ''}${regionParam(current.region)}`;
  return { ...current, query, regionQuery: regionParam(current.region), setScope: setAnalysisScope };
}
