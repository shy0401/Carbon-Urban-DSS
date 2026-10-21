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

/** 링크(주소)가 분석 지역을 바꾼 기록: 머리에 알림을 띄우고 이전 지역으로 되돌릴 수 있게 한다(UX 검토 F9). */
export type LinkedRegionChange = { from: string | null; to: string | null };
let linkChange: LinkedRegionChange | null = null;
const linkListeners = new Set<() => void>();

export function setAnalysisScope(next: Partial<Scope>, options: { fromLink?: boolean } = {}) {
  // A grid belongs to one region: switching the region clears the selected grid.
  const regionChanged = next.region !== undefined && next.region !== scope.region;
  if (regionChanged && options.fromLink) { linkChange = { from: scope.region, to: next.region ?? null }; linkListeners.forEach((fn) => fn()); }
  scope = { ...scope, ...next, ...(regionChanged && next.gridId === undefined ? { gridId: null } : {}) };
  try { localStorage.setItem('carbon-analysis-scope', JSON.stringify(scope)); } catch { /* Private mode still works in memory. */ }
  listeners.forEach((fn) => fn());
}

export function dismissLinkedRegionChange() { linkChange = null; linkListeners.forEach((fn) => fn()); }

export function useLinkedRegionChange(): LinkedRegionChange | null {
  return useSyncExternalStore((fn) => { linkListeners.add(fn); return () => linkListeners.delete(fn); }, () => linkChange, () => linkChange);
}

/** `region=…` query part (empty for the original region). */
export function regionParam(region: string | null, prefix = '&') { return region ? `${prefix}region=${encodeURIComponent(region)}` : ''; }

export function useAnalysisScope() {
  const current = useSyncExternalStore((fn) => { listeners.add(fn); return () => listeners.delete(fn); }, () => scope);
  const query = `year=${current.year}${current.gridId ? `&grid_id=${encodeURIComponent(current.gridId)}` : ''}${regionParam(current.region)}`;
  return { ...current, query, regionQuery: regionParam(current.region), setScope: setAnalysisScope };
}
