import { useSyncExternalStore } from 'react';
type Scope = { year: number; gridId: string | null };
let scope: Scope = { year: 2025, gridId: null };
try { const saved=JSON.parse(localStorage.getItem('carbon-analysis-scope') || 'null'); if(saved && Number.isInteger(saved.year) && saved.year>=2000 && saved.year<=2100) scope={year:saved.year,gridId:typeof saved.gridId==='string'?saved.gridId:null}; } catch { /* Optional browser storage. */ }
const listeners=new Set<()=>void>();
export function setAnalysisScope(next: Partial<Scope>) {
  scope={...scope,...next};
  try {localStorage.setItem('carbon-analysis-scope',JSON.stringify(scope));} catch { /* Private mode still works in memory. */ }
  listeners.forEach(fn=>fn());
}
export function useAnalysisScope() {
  const current=useSyncExternalStore(fn=>{listeners.add(fn);return ()=>listeners.delete(fn);},()=>scope);
  const query=`year=${current.year}${current.gridId?`&grid_id=${encodeURIComponent(current.gridId)}`:''}`;
  return {...current,query,setScope:setAnalysisScope};
}
